"""Individual review nodes executed by the LangGraph pipeline."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent.schemas import Finding, ReviewResult, ReviewState
from app.config import settings
from app.github.client import get_readme


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
    "list and approved=true. You may be given the repository's README as "
    "background on the project's purpose — use it only to understand intent and "
    "context, never as code to review or flag findings in."
)

SCALABILITY_SYSTEM_PROMPT = (
    "You are a senior backend engineer reviewing a pull request diff for scalability "
    "and performance concerns: N+1 queries, unbounded loops/pagination, blocking "
    "calls inside async code, missing indexes, and unbounded memory growth. Only "
    "report issues you can point to specific lines for. If nothing is wrong, return "
    "an empty findings list and approved=true. You may be given the repository's "
    "README as background on the project's purpose — use it only to understand "
    "intent and context, never as code to review or flag findings in."
)


async def build_context(state: ReviewState) -> dict:
    """Enrich the diff with repository context before it's handed to the review lenses.

    Fetches the root README.md at head_sha so the review nodes have background
    on the project's purpose — it's kept separate from the diff and never
    treated as code to analyse.
    """
    readme = await get_readme(state.owner, state.repo, state.head_sha, state.token)
    return {"repository_readme": readme}


async def _run_review(state: ReviewState, system_prompt: str) -> ReviewResult:
    llm = _get_llm().with_structured_output(ReviewResult)
    content_parts = []
    if state.repository_readme:
        content_parts.append(
            "Project context (README.md, background only — do not review or "
            f"flag findings in this text):\n{state.repository_readme}"
        )
    content_parts.append(f"Review this diff:\n\n{state.diff}")

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(content_parts)),
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
