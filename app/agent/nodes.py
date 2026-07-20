"""Individual review nodes executed by the LangGraph pipeline."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent.schemas import Finding, ReviewResult, ReviewState
from app.config import settings


def _get_llm() -> BaseChatModel:
    """Build a fresh ``ChatOpenAI`` client. Not memoized — API key/model can
    change between calls (e.g. in tests), and LangChain clients are cheap to
    construct (no network I/O happens until the first invocation).
    """
    return ChatOpenAI(model=settings.llm_model_name, api_key=settings.openai_api_key, temperature=0)


SECURITY_SYSTEM_PROMPT = (
    "You are a senior application security engineer reviewing a pull request diff. "
    "Flag injection risks, hardcoded secrets, auth/authorization gaps, unsafe "
    "deserialization, and any OWASP Top 10 concern. Only report issues you can "
    "point to specific lines for. If nothing is wrong, return an empty findings "
    "list and approved=true."
)

SCALABILITY_SYSTEM_PROMPT = (
    "You are a senior backend engineer reviewing a pull request diff for scalability "
    "and performance concerns: N+1 queries, unbounded loops/pagination, blocking "
    "calls inside async code, missing indexes, and unbounded memory growth. Only "
    "report issues you can point to specific lines for. If nothing is wrong, return "
    "an empty findings list and approved=true."
)


async def build_context(state: ReviewState) -> dict:
    """Prepare/normalize the diff before it's handed to the review lenses.

    Currently a passthrough — the diff produced by ``app.github.client.fetch_diff``
    is already a unified diff string. This node exists as the graph's designated
    place to add context enrichment later (e.g. fetching full file contents for
    changed hunks) without touching the review nodes themselves.
    """
    return {}


async def _run_review(state: ReviewState, system_prompt: str) -> ReviewResult:
    llm = _get_llm().with_structured_output(ReviewResult)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Review this diff:\n\n{state.diff}"),
    ]
    return await llm.ainvoke(messages)


async def security_review(state: ReviewState) -> dict:
    """Analyse the diff for security vulnerabilities (injection, secrets, etc.)."""
    return {"security": await _run_review(state, SECURITY_SYSTEM_PROMPT)}


async def scalability_review(state: ReviewState) -> dict:
    """Assess scalability concerns: N+1 queries, unbounded loops, sync blockers."""
    return {"scalability": await _run_review(state, SCALABILITY_SYSTEM_PROMPT)}


async def aggregate_and_rank(state: ReviewState) -> dict:
    """Merge all lens outputs into one ``ReviewResult``, ranked by severity.

    Deterministic (no LLM call): the individual lenses already produced
    structured findings, so this node just combines and orders them.
    """
    severity_rank = {"critical": 0, "warning": 1, "suggestion": 2}

    all_findings: list[Finding] = [
        *state.security.findings,
        *state.scalability.findings,
    ]
    all_findings.sort(key=lambda finding: severity_rank[finding.severity])

    approved = state.security.approved and state.scalability.approved

    summary_parts = [
        part
        for part in (state.security.summary, state.scalability.summary)
        if part
    ]
    summary = " ".join(summary_parts) or "No issues found."

    aggregated = ReviewResult(summary=summary, findings=all_findings, approved=approved)
    return {"aggregated": aggregated}


async def format_output(state: ReviewState) -> dict:
    """Render the aggregated ``ReviewResult`` into the GitHub review payload shape
    expected by ``app.github.client.post_review``.
    """
    result = state.aggregated or ReviewResult()

    body_lines = [result.summary, ""]
    for finding in result.findings:
        body_lines.append(
            f"**[{finding.severity.upper()}] {finding.file}:{finding.line}** ({finding.category})\n"
            f"{finding.description}\n"
            f"_Suggested fix:_ {finding.recommendation}"
        )

    comments = [
        {
            "path": finding.file,
            "line": finding.line,
            "body": f"**[{finding.severity.upper()}] {finding.category}**\n{finding.description}\n\n_Suggested fix:_ {finding.recommendation}",
        }
        for finding in result.findings
    ]

    return {
        "output": {
            "event": "APPROVE" if result.approved else "REQUEST_CHANGES",
            "body": "\n\n".join(body_lines),
            "comments": comments,
        }
    }
