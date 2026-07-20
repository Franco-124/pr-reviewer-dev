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
    recommendation: str = Field(description="Concrete suggested fix")


class ReviewResult(BaseModel):
    summary: str = Field(default="", description="High-level overview of the review")
    findings: list[Finding] = Field(default_factory=list)
    approved: bool = True


class ReviewState(BaseModel):
    diff: str = ""
    pr_url: str = ""
    head_sha: str = ""
    owner: str = ""
    repo: str = ""
    token: str = Field(default="", description="Installation access token, used by build_context for GitHub API calls")
    repository_readme: str | None = Field(
        default=None, description="Root README.md at head_sha, fetched by build_context; None if absent"
    )
    security: ReviewResult = Field(default_factory=ReviewResult)
    scalability: ReviewResult = Field(default_factory=ReviewResult)
    aggregated: ReviewResult | None = Field(
        default=None, description="Merged, severity-ranked output of aggregate_and_rank"
    )
    output: dict | None = Field(
        default=None, description="Final GitHub review payload produced by format_output"
    )
