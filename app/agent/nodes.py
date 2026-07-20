"""Individual review nodes executed by the LangGraph pipeline."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent.schemas import Finding, ReviewResult, ReviewState
from app.config import settings
from app.github.client import get_readme
from app.storage.findings import get_seen_fingerprints, split_new_and_recurring


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

STYLE_SYSTEM_PROMPT = (
    "You are a senior engineer reviewing a pull request diff for code style and "
    "project conventions: inconsistent naming, dead code, missing type hints on "
    "new public functions, overly complex or hard-to-read constructs, and clear "
    "violations of the language's idioms. This project is Python. Do not flag "
    "purely subjective nitpicks with no real readability impact. Only report "
    "issues you can point to specific lines for. If nothing is wrong, return an "
    "empty findings list and approved=true. You may be given the repository's "
    "README as background on the project's purpose — use it only to understand "
    "intent and context, never as code to review or flag findings in."
)

CORRECTNESS_SYSTEM_PROMPT = (
    "You are a senior software engineer reviewing a pull request diff for "
    "functional correctness: incorrect logic, off-by-one errors, unhandled edge "
    "cases, wrong API usage, broken control flow, and behavior that contradicts "
    "the apparent intent of the surrounding code. This is not a security or "
    "performance review — focus purely on whether the code does what it appears "
    "to intend to do. Only report issues you can point to specific lines for. If "
    "nothing is wrong, return an empty findings list and approved=true. You may "
    "be given the repository's README as background on the project's purpose — "
    "use it only to understand intent and context, never as code to review or "
    "flag findings in."
)

CRITIQUE_INSTRUCTIONS = (
    "Critically re-examine the findings you just drafted against the diff above. "
    "Drop any that are false positives, speculative, not clearly supported by the "
    "diff, or out of scope for your role. Adjust severity where it's overstated "
    "or understated. Do not invent new findings you didn't already report. Return "
    "the final, refined result."
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
    """Draft findings for one lens, then a second pass has the same model critique
    and refine its own draft (drop false positives, correct severity) before it's
    accepted. Two LLM calls per lens, in exchange for materially fewer false
    positives reaching the PR.
    """
    llm = _get_llm().with_structured_output(ReviewResult)
    content_parts = []
    if state.repository_readme:
        content_parts.append(
            "Project context (README.md, background only — do not review or "
            f"flag findings in this text):\n{state.repository_readme}"
        )
    content_parts.append(f"Review this diff:\n\n{state.diff}")
    review_prompt = "\n\n".join(content_parts)

    draft = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=review_prompt),
        ]
    )

    refined = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=review_prompt),
            AIMessage(content=draft.model_dump_json()),
            HumanMessage(content=CRITIQUE_INSTRUCTIONS),
        ]
    )
    return refined


async def security_review(state: ReviewState) -> dict:
    """Analyse the diff for security vulnerabilities (injection, secrets, etc.)."""
    return {"security": await _run_review(state, SECURITY_SYSTEM_PROMPT)}


async def scalability_review(state: ReviewState) -> dict:
    """Assess scalability concerns: N+1 queries, unbounded loops, sync blockers."""
    return {"scalability": await _run_review(state, SCALABILITY_SYSTEM_PROMPT)}


async def style_review(state: ReviewState) -> dict:
    """Check code style, naming, and project conventions."""
    return {"style": await _run_review(state, STYLE_SYSTEM_PROMPT)}


async def correctness_review(state: ReviewState) -> dict:
    """Assess functional correctness: logic bugs, edge cases, wrong API usage."""
    return {"correctness": await _run_review(state, CORRECTNESS_SYSTEM_PROMPT)}


async def aggregate_and_rank(state: ReviewState) -> dict:
    """Merge all lens outputs into one ``ReviewResult``, ranked by severity, and
    split out which findings are new vs. already reported on a prior push to
    this same PR (so ``format_output`` doesn't re-post duplicate inline comments).

    Deterministic aside from the DB lookup: the individual lenses already
    produced structured findings, so this node just combines, ranks, and dedupes.
    """
    severity_rank = {"critical": 0, "warning": 1, "suggestion": 2}

    lenses = [state.security, state.scalability, state.style, state.correctness]

    all_findings: list[Finding] = [finding for lens in lenses for finding in lens.findings]
    all_findings.sort(key=lambda finding: severity_rank[finding.severity])

    approved = all(lens.approved for lens in lenses)

    summary_parts = [lens.summary for lens in lenses if lens.summary]
    summary = " ".join(summary_parts) or "No issues found."

    seen = await get_seen_fingerprints(state.pr_id)
    new_findings, recurring_findings = split_new_and_recurring(all_findings, seen)
    if recurring_findings:
        summary += f" ({len(recurring_findings)} previously reported finding(s) remain unresolved.)"

    aggregated = ReviewResult(summary=summary, findings=all_findings, approved=approved)
    return {"aggregated": aggregated, "new_findings": new_findings}


async def format_output(state: ReviewState) -> dict:
    """Render the aggregated ``ReviewResult`` into the GitHub review payload shape
    expected by ``app.github.client.post_review``.

    Inline comments are only posted for ``new_findings`` — recurring findings
    already have a comment from a prior review of this PR, so re-posting them
    on every push would just spam duplicate comments on the same line.
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
        for finding in state.new_findings
    ]

    return {
        "output": {
            "event": "APPROVE" if result.approved else "REQUEST_CHANGES",
            "body": "\n\n".join(body_lines),
            "comments": comments,
        }
    }
