"""GitHub API client — fetch diffs, post reviews, manage comments."""

from __future__ import annotations


async def fetch_diff(pull_url: str) -> str:
    """Retrieve the unified diff for a pull request."""
    ...


async def post_review(review_payload: dict) -> dict:
    """Submit a pull request review with inline comments."""
    ...
