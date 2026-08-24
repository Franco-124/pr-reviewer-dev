# Development Guide

## Local setup

```bash
python -m venv venv
source venv/Scripts/activate      # Git Bash / PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env               # fill in values, see CONFIGURATION.md
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

To receive real GitHub webhooks locally, tunnel the port (e.g. `ngrok http 8000`) and set the tunnel URL as your GitHub App's webhook URL.

## Tests

```bash
pytest                                                        # full suite
pytest tests/github/test_signature.py                         # one file
pytest tests/github/test_signature.py::test_verify_signature_valid  # one test
```

Existing coverage: `tests/github/test_signature.py` (HMAC signature verification — valid, tampered, wrong secret, malformed header) and `tests/storage/test_idempotency.py` (idempotency store, using a `tmp_path`-backed SQLite file per test via the `db_path` fixture). There is no coverage yet for `app/agent/nodes.py`, `app/github/client.py`, `app/github/auth.py`, or `app/storage/findings.py`.

When adding tests for storage modules, follow the existing pattern: every storage function accepts an optional `db_path` parameter (defaults to `settings.db_path`) specifically so tests can point at an isolated `tmp_path` SQLite file instead of the real `idempotency.db`.

## Lint

```bash
ruff check .
```

## Extending the review pipeline

To add a new review lens (e.g. a "docs" lens):

1. Add a `<lens>: ReviewResult = Field(default_factory=ReviewResult)` field to `ReviewState` in `app/agent/schemas.py`.
2. Write a `<LENS>_SYSTEM_PROMPT` constant and a `<lens>_review(state) -> dict` node in `app/agent/nodes.py`, following the existing lenses — call `_run_review(state, <LENS>_SYSTEM_PROMPT, "<Lens>")` and return `{"<lens>": result}`.
3. Add the new node to `LENS_NODES` in `app/agent/graph.py` — it's wired into the parallel fan-out/fan-in automatically (`build_context -> new_node -> aggregate_and_rank`), no other graph changes needed.
4. Add `state.<lens>` to the `lenses` list in `aggregate_and_rank()` (`app/agent/nodes.py`) so its findings get merged into the aggregated result.

To change the merge gate or scoring, edit `_compute_verdict` / `_compute_merge_readiness` and `_SEVERITY_PENALTY` in `app/agent/nodes.py` — both are deterministic, plain-Python functions independent of any LLM output.

## Project conventions

- Type hints everywhere; `from __future__ import annotations` at the top of every module.
- Pydantic models (`app/agent/schemas.py`) are the structured-output contract for every LLM call (`.with_structured_output(ReviewResult)`) — new fields on `Finding`/`ReviewResult` propagate automatically into what the LLM is asked to produce.
- Module boundaries are intentional and should be preserved: signature verification stays in `app/github/signature.py`; GitHub HTTP calls stay in `app/github/client.py` / `auth.py`; review logic stays inside LangGraph nodes in `app/agent/nodes.py`, never in the webhook handler.
- Every storage/GitHub-client function logs at `debug` on entry, `info` on success, `error`/`warning` on failure — keep new functions consistent with this so `logs/pr_reviewer_errors.log` stays a reliable single source for failures.
- Errors in `process_pull_request` (the background task) are caught and logged, never re-raised — there is no caller to propagate to. Don't add a bare `except` inside a lens node or storage function that would silently absorb an error instead — let it raise up to `process_pull_request`'s single catch-all.

## Deployment

Configured for [Render](https://render.com) via [render.yaml](render.yaml): a free-tier Python web service running `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Secrets (`GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_PRIVATE_KEY`, `OPENAI_API_KEY`) are set manually in the Render dashboard (`sync: false`). Use `GITHUB_PRIVATE_KEY` (raw PEM contents), not `GITHUB_PRIVATE_KEY_PATH`, since Render's filesystem is ephemeral.

`idempotency.db` (SQLite) is a local file on the instance — on Render's free tier this does **not** persist across deploys/restarts, so idempotency and findings-history state resets on redeploy. For persistent storage in production, attach a persistent disk or migrate to an external database.
