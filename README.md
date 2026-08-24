# PR Review Agent

FastAPI service that runs as a GitHub App: it receives `pull_request` webhook events, fetches the diff, runs it through a multi-lens LangGraph review pipeline (security, scalability, style, correctness), and posts the aggregated result back to GitHub as a PR review with inline comments and a deterministic merge verdict.

## Table of Contents

- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Commands](#commands)
- [How It Works](#how-it-works)
- [Further Documentation](#further-documentation)

## Quick Start

```bash
# 1. Create and activate the venv
python -m venv venv
source venv/Scripts/activate   # Git Bash / PowerShell: venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# fill in GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, GITHUB_WEBHOOK_SECRET,
# GITHUB_PRIVATE_KEY_PATH (or GITHUB_PRIVATE_KEY), OPENAI_API_KEY

# 4. Run the API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The service exposes a single webhook endpoint at `POST /webhooks/github`. Point your GitHub App's webhook URL at it (e.g. via `ngrok` for local dev).

## Prerequisites

- Python 3.12
- A registered GitHub App with:
  - Permissions: `Pull requests: Read & write`, `Contents: Read-only`
  - Subscribed webhook event: `Pull request`
  - A generated private key (`.pem`)
- An OpenAI API key

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_APP_ID` | yes | — | GitHub App ID |
| `GITHUB_APP_INSTALLATION_ID` | yes | — | Installation ID of the App on the target repo/org |
| `GITHUB_WEBHOOK_SECRET` | yes | — | Secret used to validate `X-Hub-Signature-256` |
| `GITHUB_PRIVATE_KEY_PATH` | one of these two | — | Path to the App's `.pem` file (local dev) |
| `GITHUB_PRIVATE_KEY` | one of these two | — | Full PEM contents as a single env var (PaaS deploys, e.g. Render) |
| `OPENAI_API_KEY` | yes | — | OpenAI API key used by every review lens |
| `LLM_MODEL_NAME` | no | `gpt-4.1-mini` | Chat model used for all four review lenses |
| `HOST` | no | `0.0.0.0` | Bind host |
| `PORT` | no | `8000` | Bind port |
| `DB_PATH` | no | `idempotency.db` | SQLite file backing both the idempotency and findings-history stores |

Exactly one of `GITHUB_PRIVATE_KEY` / `GITHUB_PRIVATE_KEY_PATH` must be set — the app refuses to start otherwise. See [CONFIGURATION.md](CONFIGURATION.md) for details.

## Commands

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000   # run locally
ruff check .                                                # lint
pytest                                                       # run all tests
pytest tests/github/test_signature.py::test_verify_signature_valid  # single test
```

## How It Works

1. GitHub sends a `pull_request` webhook (`opened` or `synchronize`) to `POST /webhooks/github`.
2. The HMAC signature is verified; the request returns `202`-style acceptance immediately and processing continues in a background task.
3. The PR diff is fetched via the GitHub REST API using a short-lived GitHub App installation token.
4. A LangGraph pipeline runs four review lenses in parallel (security, scalability, style, correctness), each doing a draft + self-critique pass with an LLM.
5. Findings are merged, deterministically scored/ranked, and diffed against previously-reported findings for the same PR (so re-pushes don't spam duplicate comments).
6. A formatted review (summary, severity table, inline comments) is posted back to GitHub via the Pull Request Reviews API.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design and [API_GUIDE.md](API_GUIDE.md) for the webhook contract.

## Further Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — internal design, review pipeline, data flow
- [API_GUIDE.md](API_GUIDE.md) — webhook endpoint contract and GitHub API usage
- [CONFIGURATION.md](CONFIGURATION.md) — full environment variable reference
- [DEVELOPMENT.md](DEVELOPMENT.md) — local setup, testing, extending the pipeline, deployment
