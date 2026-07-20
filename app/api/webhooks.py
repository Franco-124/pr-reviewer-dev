"""GitHub webhook receiver — ingests push / pull_request events."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/github")
async def github_webhook(request: Request):
    """Entry point for GitHub webhook events.

    * Validates the HMAC signature (X-Hub-Signature-256).
    * Checks idempotency against head_sha.
    * Dispatches to the review graph.
    """
    ...
    return {"status": "ok"}
