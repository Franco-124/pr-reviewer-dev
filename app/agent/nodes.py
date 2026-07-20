"""Individual review nodes executed by the LangGraph pipeline."""

from __future__ import annotations

from app.agent.schemas import ReviewState


async def security_review(state: ReviewState) -> dict:
    """Analyse the diff for security vulnerabilities (injection, secrets, etc.)."""
    ...


async def scalability_review(state: ReviewState) -> dict:
    """Assess scalability concerns: N+1 queries, unbounded loops, sync blockers."""
    ...


async def style_review(state: ReviewState) -> dict:
    """Check code style, naming, and project conventions."""
    ...


async def aggregate_review(state: ReviewState) -> dict:
    """Merge all node outputs into a single structured GitHub review."""
    ...
