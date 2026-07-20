"""Pydantic models for structured review output and graph state."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    file: str = Field(description="Path of the affected file, relative to the repo root")
    line: int = Field(description="1-indexed line number the finding applies to")
    severity: Literal["critical", "warning", "suggestion"]
    category: str = Field(description="Lens that produced the finding, e.g. 'security', 'scalability', 'style'")
    description: str = Field(description="What the issue is and why it matters")
    recommendation: str = Field(
        description="Concrete, actionable fix — specific enough that a developer could apply it "
        "without further investigation (name the exact function/pattern to use, not just 'validate input')"
    )
    confidence: int = Field(
        ge=0, le=100,
        description="0-100: how confident you are this is a real, non-speculative issue given only the diff. "
        "Below 50 means you're unsure it's actually a problem — only include it if severity is 'suggestion'.",
    )


class ReviewResult(BaseModel):
    summary: str = Field(default="", description="High-level overview of the review")
    findings: list[Finding] = Field(default_factory=list)
    approved: bool = True


class ReviewState(BaseModel):
    diff: str = ""
    pr_url: str = ""
    head_sha: str = ""
    pr_id: int = Field(default=0, description="GitHub's internal PR id, used to look up findings from prior reviews")
    owner: str = ""
    repo: str = ""
    token: str = Field(default="", description="Installation access token, used by build_context for GitHub API calls")
    repository_readme: str | None = Field(
        default=None, description="Root README.md at head_sha, fetched by build_context; None if absent"
    )
    security: ReviewResult = Field(default_factory=ReviewResult)
    scalability: ReviewResult = Field(default_factory=ReviewResult)
    style: ReviewResult = Field(default_factory=ReviewResult)
    correctness: ReviewResult = Field(default_factory=ReviewResult)
    aggregated: ReviewResult | None = Field(
        default=None, description="Merged, severity-ranked output of aggregate_and_rank (all findings, new + recurring)"
    )
    new_findings: list[Finding] = Field(
        default_factory=list,
        description="Subset of aggregated.findings not already posted on a prior review of this PR",
    )
    merge_readiness_score: int = Field(
        default=100, ge=0, le=100,
        description="Deterministic 0-100 score computed in aggregate_and_rank from finding "
        "counts/severity — NOT decided by the LLM.",
    )
    verdict: Literal["approve", "request_changes"] = Field(
        default="approve",
        description="Deterministic merge gate computed in aggregate_and_rank: any 'critical' "
        "finding forces request_changes regardless of what any lens's own approved flag says.",
    )
    output: dict | None = Field(
        default=None, description="Final GitHub review payload produced by format_output"
    )
