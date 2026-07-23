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
    logger.debug(f"Received webhook request (payload size: {len(raw_body)} bytes)")

    if not verify_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret):
        logger.warning("Webhook signature validation failed - rejecting request")
        raise HTTPException(status_code=401, detail="Invalid signature")

    logger.debug("✓ Webhook signature validation passed")

    payload = await request.json()
    action = payload.get("action")
    logger.info(f"Received GitHub event: type={x_github_event}, action={action}")

    if x_github_event != "pull_request" or action not in HANDLED_ACTIONS:
        logger.info(f"Ignoring event: event_type={x_github_event}, action={action} (not in {HANDLED_ACTIONS})")
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

    logger.info(
        f"Processing PR: {owner}/{repo}#{pull_number} "
        f"(id={pr_id}, sha={head_sha[:8]}..., installation={installation_id})"
    )

    background_tasks.add_task(
        process_pull_request, owner, repo, pull_number, pr_id, pr_url, head_sha, installation_id
    )

    logger.debug("✓ Background task scheduled for PR review")
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
    logger.info(f"[{owner}/{repo}#{pull_number}] Starting PR review pipeline")

    try:
        logger.debug(f"[{owner}/{repo}#{pull_number}] Checking idempotency (pr_id={pr_id}, sha={head_sha[:8]}...)")
        if await is_processed(pr_id, head_sha):
            logger.info(f"[{owner}/{repo}#{pull_number}] ⊘ Skipping: PR already reviewed at this sha")
            return

        logger.debug(f"[{owner}/{repo}#{pull_number}] Generating GitHub App installation token")
        token = await get_installation_token(str(installation_id))
        logger.debug(f"[{owner}/{repo}#{pull_number}] ✓ Installation token obtained")

        logger.debug(f"[{owner}/{repo}#{pull_number}] Fetching PR diff (pull_number={pull_number})")
        diff = await fetch_diff(owner, repo, pull_number, token)
        logger.info(f"[{owner}/{repo}#{pull_number}] ✓ Diff fetched ({len(diff)} bytes)")

        logger.debug(f"[{owner}/{repo}#{pull_number}] Building review state")
        state = ReviewState(
            diff=diff,
            pr_url=pr_url,
            head_sha=head_sha,
            pr_id=pr_id,
            owner=owner,
            repo=repo,
            token=token,
        )

        logger.info(f"[{owner}/{repo}#{pull_number}] Running review graph (security, scalability, style, correctness)")
        graph = build_review_graph()
        result = await graph.ainvoke(state)
        logger.info(
            f"[{owner}/{repo}#{pull_number}] ✓ Review pipeline completed "
            f"(verdict={result.get('verdict', '?')}, "
            f"readiness={result.get('merge_readiness_score', '?')}%)"
        )

        logger.debug(
            f"[{owner}/{repo}#{pull_number}] Posting review to GitHub "
            f"(event={result['output'].get('event')}, "
            f"{len(result['output'].get('comments', []))} inline comments)"
        )
        review = await post_review(owner, repo, pull_number, token, result["output"])
        logger.info(f"[{owner}/{repo}#{pull_number}] ✓ Review posted to GitHub (review_id={review['id']})")

        logger.debug(f"[{owner}/{repo}#{pull_number}] Marking PR as processed in idempotency store")
        await mark_processed(pr_id, head_sha, review_id=review["id"])
        logger.debug(f"[{owner}/{repo}#{pull_number}] ✓ Idempotency marker saved")

        logger.debug(f"[{owner}/{repo}#{pull_number}] Saving findings to database ({len(result['aggregated'].findings)} findings)")
        await save_findings(pr_id, head_sha, result["aggregated"].findings)
        logger.info(f"[{owner}/{repo}#{pull_number}] ✓ PR review complete and findings saved")

    except Exception as e:
        logger.exception(
            f"[{owner}/{repo}#{pull_number}] ✗ FAILED to process PR (sha={head_sha[:8]}...). "
            f"Error type: {type(e).__name__}, Message: {str(e)}"
        )
