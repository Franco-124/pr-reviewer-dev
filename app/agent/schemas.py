"""Pydantic models for structured review output and graph state."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    line: int
    severity: Literal["critical", "warning", "suggestion"]
    message: str


class ReviewOutput(BaseModel):
    summary: str = Field(description="High-level overview of the review")
    findings: list[Finding] = Field(default_factory=list)
    approved: bool = True


class ReviewState(BaseModel):
    diff: str = ""
    pr_url: str = ""
    head_sha: str = ""
    security: ReviewOutput = Field(default_factory=ReviewOutput)
    scalability: ReviewOutput = Field(default_factory=ReviewOutput)
    style: ReviewOutput = Field(default_factory=ReviewOutput)
