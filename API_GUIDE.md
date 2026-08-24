# API Guide

## Webhook endpoint

### `POST /webhooks/github`

Single entry point for the service. Designed to receive GitHub App webhook deliveries — configure this as the App's webhook URL.

**Headers**

| Header | Required | Description |
|---|---|---|
| `X-Hub-Signature-256` | yes | HMAC-SHA256 of the raw request body, hex-encoded, prefixed `sha256=`. Signed with `GITHUB_WEBHOOK_SECRET`. Missing/invalid → `401`. |
| `X-GitHub-Event` | yes | GitHub event type, e.g. `pull_request`. Anything other than `pull_request` is accepted (`200`) but ignored. |

**Body**: raw GitHub webhook JSON payload for a `pull_request` event.

**Behavior**

1. Verifies `X-Hub-Signature-256` against the raw body using `app/github/signature.py::verify_signature`. On failure: `401 {"detail": "Invalid signature"}`.
2. Filters on `X-GitHub-Event == "pull_request"` and `payload.action in {"opened", "synchronize"}`. Any other event/action is acknowledged but not processed.
3. On a match, schedules `process_pull_request` as a `BackgroundTasks` job and returns immediately.

**Responses**

| Status | Body | When |
|---|---|---|
| `200` | `{"status": "accepted"}` | Valid signature, matching event/action — review scheduled |
| `200` | `{"status": "ignored", "event": "...", "action": "..."}` | Valid signature, non-matching event/action |
| `401` | `{"detail": "Invalid signature"}` | Missing or invalid `X-Hub-Signature-256` |

**Example**

```bash
BODY='{"action":"opened","pull_request":{...},"repository":{...},"installation":{"id":123}}'
SIG="sha256=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$GITHUB_WEBHOOK_SECRET" | sed 's/^.* //')"

curl -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: pull_request" \
  -H "X-Hub-Signature-256: $SIG" \
  -d "$BODY"
```

Note: the endpoint returning `200`/`202` only confirms the webhook was accepted and scheduled — it does **not** guarantee the review succeeded. Failures during `process_pull_request` (diff fetch, LLM call, posting the review) are logged but not surfaced back to GitHub; check `logs/pr_reviewer_errors.log`.

## Outbound: GitHub REST API usage

The service is also a GitHub API *client*, authenticating as the GitHub App installation (`app/github/auth.py`, `app/github/client.py`):

| Call | Endpoint | Purpose |
|---|---|---|
| `get_installation_token` | `POST /app/installations/{id}/access_tokens` | Exchange the App JWT for a 1-hour installation token |
| `fetch_pr_files` | `GET /repos/{owner}/{repo}/pulls/{pr}/files` (paginated) | List changed files + unified diff patches |
| `fetch_diff` | (built from `fetch_pr_files`) | Reassembles a unified diff from per-file patches |
| `fetch_file_content` | `GET /repos/{owner}/{repo}/contents/{path}?ref={ref}` | Fetch full content of a file at a ref |
| `get_readme` | `GET /repos/{owner}/{repo}/contents/README.md?ref={ref}` | Fetch root README at `head_sha` (404 → `None`) |
| `post_review` | `POST /repos/{owner}/{repo}/pulls/{pr}/reviews` | Submit the aggregated review (`event`, `body`, `comments`) |

All calls use `Authorization: Bearer <installation_token>` and `X-GitHub-Api-Version: 2022-11-28`.

### `post_review` payload shape

```json
{
  "event": "APPROVE | REQUEST_CHANGES",
  "body": "## PR Review — ...(markdown)...",
  "comments": [
    {"path": "app/foo.py", "line": 42, "body": "🔴 Critical · security · 92% confidence\n\n...markdown..."}
  ]
}
```

`comments` only includes `new_findings` (not previously reported on this PR) — see [ARCHITECTURE.md](ARCHITECTURE.md#storage).
