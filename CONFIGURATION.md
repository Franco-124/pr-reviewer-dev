# Configuration

Loaded via `pydantic-settings` (`app/config.py`) from a `.env` file at the repo root (or real environment variables — env vars take precedence over `.env`). Unknown keys are ignored (`extra="ignore"`). Validation runs at import time — a missing required variable exits the process with a clear error message instead of failing later at first use.

## Variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `GITHUB_APP_ID` | yes | — | Numeric GitHub App ID, used as the JWT `iss` claim |
| `GITHUB_APP_INSTALLATION_ID` | yes | — | Installation ID for the target repo/org |
| `GITHUB_WEBHOOK_SECRET` | yes | — | Shared secret configured on the GitHub App's webhook, used to validate `X-Hub-Signature-256` |
| `GITHUB_PRIVATE_KEY_PATH` | conditionally | `""` | Path to the App's `.pem` file. Used for local development. |
| `GITHUB_PRIVATE_KEY` | conditionally | `""` | Full PEM contents as a single env var (newlines included as-is). Used for deploys with an ephemeral filesystem, e.g. Render. |
| `OPENAI_API_KEY` | yes | — | Passed to every `ChatOpenAI` instance |
| `LLM_MODEL_NAME` | no | `gpt-4.1-mini` | Model used for all four review lenses (temperature fixed at `0`) |
| `HOST` | no | `0.0.0.0` | Bind host (only consulted when running `uvicorn` with `settings.host`; `uvicorn` CLI flags override this if passed explicitly) |
| `PORT` | no | `8000` | Bind port |
| `DB_PATH` | no | `idempotency.db` | SQLite file shared by both the idempotency and findings-history tables |

Exactly one of `GITHUB_PRIVATE_KEY` / `GITHUB_PRIVATE_KEY_PATH` must be non-empty — `Settings._require_private_key_source` raises otherwise, and startup fails with:

```
Missing required environment variable(s): ...
```
or the validator's own message if only the private-key pair is the issue.

## Per-environment setup

**Local development** — use `.env` with `GITHUB_PRIVATE_KEY_PATH` pointing at the App's `.pem` file (the `.pem` and `.env` are both gitignored — never commit them).

**Render (or other ephemeral-filesystem PaaS)** — see [render.yaml](render.yaml): all secrets are set as dashboard env vars (`sync: false`), and `GITHUB_PRIVATE_KEY` (the raw PEM content) is used instead of `GITHUB_PRIVATE_KEY_PATH`, since there's no persistent file to point at. `LLM_MODEL_NAME` is pinned to `gpt-4.1-mini` in `render.yaml`.

## Secrets handling

- `.env`, `*.pem`, and `idempotency.db` are gitignored — never read, print, or commit them.
- The private key never leaves `app/github/auth.py` — it's loaded on-demand inside `_load_private_key()` for each JWT signing call, not cached at import time.
