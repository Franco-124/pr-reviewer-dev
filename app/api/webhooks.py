"""GitHub webhook receiver — ingests push / pull_request events."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.agent.graph import build_review_graph
from app.agent.schemas import ReviewState
from app.config import settings
from app.github.auth import get_installation_token
from app.github.client import fetch_diff, post_review
from app.github.signature import verify_signature
from app.storage.findings import save_findings
from app.storage.idempotency import is_processed, mark_processed

logger = logging.getLogger(__name__)

router = APIRouter()

HANDLED_ACTIONS = {"opened", "synchronize"}


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
):
    """Entry point for GitHub webhook events.

    * Validates the HMAC signature (X-Hub-Signature-256).
    * Filters to `pull_request` events with action in {opened, synchronize}.
    * Dispatches processing to a background task and returns immediately.
    """
    raw_body = await request.body()

    if not verify_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    action = payload.get("action")
    logger.info("Received event=%s action=%s", x_github_event, action)

    if x_github_event != "pull_request" or action not in HANDLED_ACTIONS:
        return {"status": "ignored", "event": x_github_event, "action": action}

    pull_request = payload.get("pull_request", {})
    repository = payload.get("repository", {})
    pr_id = pull_request.get("id")
    pr_url = pull_request.get("url", "")
    pull_number = pull_request.get("number")
    head_sha = pull_request.get("head", {}).get("sha", "")
    owner = repository.get("owner", {}).get("login", "")
    repo = repository.get("name", "")
    installation_id = payload.get("installation", {}).get("id")

    background_tasks.add_task(
        process_pull_request, owner, repo, pull_number, pr_id, pr_url, head_sha, installation_id
    )

    return {"status": "accepted"}


async def process_pull_request(
    owner: str,
    repo: str,
    pull_number: int,
    pr_id: int,
    pr_url: str,
    head_sha: str,
    installation_id: int | str,
) -> None:
    """Run the review pipeline for a single PR and post the result back to GitHub.

    Runs as a FastAPI ``BackgroundTask`` after the webhook response has already
    been sent — errors here do not propagate to the caller, so they must be
    logged explicitly.

    Flow: idempotency check -> fetch diff (context) -> agent graph -> post
    review -> mark as processed.
    """
    try:
        if await is_processed(pr_id, head_sha):
            logger.info("Skipping already-reviewed PR %s at sha=%s", pr_url, head_sha)
            return

        token = await get_installation_token(str(installation_id))
        diff = await fetch_diff(owner, repo, pull_number, token)

        state = ReviewState(
            diff=diff,
            pr_url=pr_url,
            head_sha=head_sha,
            pr_id=pr_id,
            owner=owner,
            repo=repo,
            token=token,
        )
        graph = build_review_graph()
        result = await graph.ainvoke(state)

        review = await post_review(owner, repo, pull_number, token, result["output"])

        await mark_processed(pr_id, head_sha, review_id=review["id"])
        await save_findings(pr_id, head_sha, result["aggregated"].findings)
    except Exception:
        logger.exception("Failed to process pull request %s (sha=%s)", pr_url, head_sha)
