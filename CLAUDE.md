# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A FastAPI service that acts as a GitHub App: it receives GitHub webhook events (PRs, pushes), fetches the diff, runs it through a LangGraph review pipeline with multiple specialized reviewer nodes, and posts the aggregated result back as a GitHub PR review. The codebase is currently a scaffold — most functions are typed stubs (`...`) with docstrings describing intended behavior, not yet implemented.

## Commands

There is no `pyproject.toml`/Makefile; use the venv and tools directly.

```bash
# activate the venv (already created at ./venv)
source venv/Scripts/activate   # Git Bash / PowerShell: venv\Scripts\Activate.ps1

# install/sync dependencies
pip install -r requirements.txt

# run the API locally
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# lint
ruff check .

# tests (pytest + pytest-asyncio are declared as deps; no tests exist yet)
pytest
pytest path/to/test_file.py::test_name   # run a single test
```

Config is loaded via `pydantic-settings` from a `.env` file (see `.env.example` for the required keys: `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY_PATH`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_WEBHOOK_SECRET`, `HOST`, `PORT`). Never read or print `.env` or `*.pem` files — the GitHub App private key lives in a `.pem` at the repo root and both are gitignored.

## Architecture

**Request flow:** `app/api/webhooks.py` (`POST /webhooks/github`) is the single entry point. It is expected to (1) verify the `X-Hub-Signature-256` HMAC via `app/github/signature.py::verify_signature`, (2) de-duplicate on `head_sha`, and (3) hand off to the LangGraph pipeline in `app/agent/`. Once a verdict is produced, `app/github/client.py::post_review` submits it back to GitHub as a PR review with inline comments.

**GitHub App auth** (`app/github/auth.py`) is a two-step token exchange: `generate_app_jwt()` signs a short-lived RS256 JWT with the App's private key, which `get_installation_token()` then exchanges for an installation-scoped access token used by `app/github/client.py` to call the GitHub REST API.

**Review pipeline** (`app/agent/`) is a LangGraph `StateGraph` over a single shared `ReviewState` (`app/agent/schemas.py`):
- `ReviewState` carries the diff, PR URL, and head SHA in, and accumulates three independent `ReviewResult` objects (`security`, `scalability`, `style`) as the graph runs.
- `app/agent/nodes.py` defines one node per review lens — `security_review`, `scalability_review`, `style_review` — each analyzing the diff from a different angle and writing into its slot of `ReviewState`. A final `aggregate_review` node merges the three `ReviewResult`s into the single review posted to GitHub.
- `ReviewResult` (summary + list of `Finding`, each with `file`/`line`/`severity`/`category`/`description`/`recommendation`) is the structured output contract every review node and the aggregator conform to.
- `app/agent/graph.py::build_review_graph()` is where these nodes get wired into the compiled graph (edges/ordering not yet implemented).

**Storage** (`app/storage/`) is an empty package — intended for the idempotency/dedup store (`aiosqlite` is a declared dependency) but not yet implemented.

When implementing a stub, keep the module boundaries as they are: signature verification stays in `app/github/signature.py`, GitHub HTTP calls stay in `app/github/client.py`/`auth.py`, and review logic stays inside LangGraph nodes in `app/agent/nodes.py` rather than in the webhook handler.
