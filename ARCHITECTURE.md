# Architecture

## Overview

```
GitHub ──webhook(pull_request)──▶ POST /webhooks/github (app/api/webhooks.py)
                                        │
                                        ├─ verify_signature() (HMAC, X-Hub-Signature-256)
                                        ├─ filter: event=pull_request, action in {opened, synchronize}
                                        └─ BackgroundTasks.add_task(process_pull_request)
                                                    │
                                                    ▼
                                    process_pull_request()
                                        │
                                        ├─ is_processed(pr_id, head_sha)?  ──▶ yes: skip (idempotency)
                                        ├─ get_installation_token()        (app/github/auth.py)
                                        ├─ fetch_diff()                    (app/github/client.py)
                                        ├─ build_review_graph().ainvoke()  (app/agent/graph.py)
                                        ├─ post_review()                   (app/github/client.py)
                                        ├─ mark_processed()                (app/storage/idempotency.py)
                                        └─ save_findings()                 (app/storage/findings.py)
```

## Review pipeline (LangGraph)

`app/agent/graph.py::build_review_graph()` compiles a `StateGraph[ReviewState]`:

```
START ──▶ build_context ──▶ security_review     ──┐
                        ├──▶ scalability_review  ──┤
                        ├──▶ style_review         ──┼──▶ aggregate_and_rank ──▶ format_output ──▶ END
                        └──▶ correctness_review   ──┘
```

- **`build_context`** — fetches the repo's root `README.md` at `head_sha` (best-effort; failures are logged and swallowed) so review lenses have project context without treating it as code to flag.
- **Four lens nodes** (`security_review`, `scalability_review`, `style_review`, `correctness_review`) — run in parallel, each backed by `_run_review()`: a **draft + self-critique** two-call pattern against the same `ChatOpenAI` model (`with_structured_output(ReviewResult)`). The second call feeds the model its own draft findings and asks it to drop false positives, correct severity, and sharpen recommendations.
- **`aggregate_and_rank`** — merges the four `ReviewResult`s into one, sorts findings by severity then confidence, and computes two things deterministically in code (never trusting the LLM's own judgment):
  - `merge_readiness_score` (0-100): starts at 100, subtracts a per-finding penalty weighted by severity (`critical=34`, `warning=10`, `suggestion=3`) and discounted by the model's own confidence.
  - `verdict` (`approve` / `request_changes`): any finding with `severity="critical"` and `confidence >= 50` forces `request_changes`, overriding any lens's own `approved` flag.
  It also diffs findings against `app/storage/findings.py` history to split `new_findings` vs. recurring ones.
- **`format_output`** — renders the final GitHub review body (verdict header, readiness score, severity-count table, findings grouped by severity) and builds the inline-comment list — **only for `new_findings`**, so unresolved findings from a prior push aren't re-posted as duplicate comments.

## State

`ReviewState` (`app/agent/schemas.py`) is the single Pydantic model threaded through every graph node. It carries the diff/PR identity in, accumulates one `ReviewResult` per lens, and ends with `aggregated`, `new_findings`, `verdict`, `merge_readiness_score`, and `output` (the final GitHub review payload).

`Finding` is the atomic unit: `file`, `line`, `severity` (`critical`/`warning`/`suggestion`), `category` (which lens produced it), `description`, `recommendation`, `confidence` (0-100, self-reported by the LLM).

## GitHub integration

- **Auth** (`app/github/auth.py`) — two-step exchange: `generate_app_jwt()` signs a 10-minute RS256 JWT with the App's private key (loaded from `GITHUB_PRIVATE_KEY` env var or `GITHUB_PRIVATE_KEY_PATH` file); `get_installation_token()` exchanges it for an installation-scoped access token (not cached — see the docstring's note on the risk of naive caching against the token's 1-hour expiry).
- **Client** (`app/github/client.py`) — `fetch_pr_files` (paginated), `fetch_diff` (rebuilds a unified diff from each file's `patch` fragment, skipping binaries/oversized files GitHub omits `patch` for), `fetch_file_content`, `get_readme` (404 treated as "no README", not an error), `post_review` (each call creates a *new* GitHub review — there's no update-in-place; re-running on the same PR adds another review rather than replacing one).
- **Signature verification** (`app/github/signature.py`) — constant-time HMAC-SHA256 comparison via `hmac.compare_digest`.

## Storage

Two independent SQLite tables in the same file (`DB_PATH`, default `idempotency.db`), each with its own `aiosqlite` connection per call (no shared pool):

- **`processed_reviews`** (`app/storage/idempotency.py`) — `(pr_id, head_sha)` primary key, `review_id`. Prevents re-reviewing the same commit twice (e.g. duplicate webhook delivery).
- **`findings`** (`app/storage/findings.py`) — every finding ever posted, keyed loosely by `(pr_id, file, line, category)` "fingerprint". Used to compute `new_findings` vs. recurring on each subsequent push to the same PR.

## Logging

`app/logging_config.py` configures a `dictConfig`-based logger: colored console output, a rotating `logs/pr_reviewer.log` (all levels, 10MB × 5 backups), and a rotating `logs/pr_reviewer_errors.log` (errors only). Third-party loggers (`httpx`, `langchain*`) are routed to file-only at `INFO` to keep the console readable. See [LOGGING.md](LOGGING.md) for the full logging design rationale.

## Design decisions

- **Deterministic gate, not LLM judgment** — `verdict` and `merge_readiness_score` are computed in plain Python from structured `Finding` data, not asked of the model directly. This makes the merge decision auditable and reproducible independent of LLM non-determinism.
- **Draft + self-critique per lens** — doubles LLM calls (4 lenses × 2 calls) in exchange for fewer false positives reaching the PR; the critique pass is instructed to only *remove or refine*, never add new findings.
- **Idempotency at (pr_id, head_sha) granularity** — a re-delivered webhook or a re-run for the same commit is a no-op, but a new push (new `head_sha`) always re-reviews the full diff even if unrelated findings are unchanged.
- **Findings history at (file, line, category) granularity** — coarse identity; a finding that shifts by one line due to unrelated edits above it will look "new" again. There's no diff-aware finding tracking.
- **Background-task processing** — the webhook handler returns immediately after signature validation and event filtering; the actual review runs in a `BackgroundTasks` job, so errors during processing are logged but never surfaced to the GitHub webhook delivery (GitHub sees a `200`/`202` regardless of downstream failure).
