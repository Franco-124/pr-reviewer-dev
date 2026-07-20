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


_SHARED_INSTRUCTIONS = (
    "Only report issues you can point to specific lines for — never speculate about "
    "code outside the diff. Every recommendation must be concrete and actionable: name "
    "the exact function, pattern, or one-line fix a developer should apply, not generic "
    "advice like 'add validation' or 'handle errors better'. Score your own confidence "
    "(0-100) on each finding honestly; if you're not sure it's a real issue, use a low "
    "confidence and 'suggestion' severity rather than omitting it or inflating severity. "
    "If nothing is wrong, return an empty findings list and approved=true. You may be "
    "given the repository's README as background on the project's purpose — use it only "
    "to understand intent and context, never as code to review or flag findings in."
)

SECURITY_SYSTEM_PROMPT = (
    "You are a senior application security engineer reviewing a pull request diff. "
    "Flag injection risks, hardcoded secrets, auth/authorization gaps, unsafe "
    "deserialization, and any OWASP Top 10 concern. " + _SHARED_INSTRUCTIONS
)

SCALABILITY_SYSTEM_PROMPT = (
    "You are a senior backend engineer reviewing a pull request diff for scalability "
    "and performance concerns: N+1 queries, unbounded loops/pagination, blocking "
    "calls inside async code, missing indexes, and unbounded memory growth. "
    + _SHARED_INSTRUCTIONS
)

STYLE_SYSTEM_PROMPT = (
    "You are a senior engineer reviewing a pull request diff for code style and "
    "project conventions: inconsistent naming, dead code, missing type hints on "
    "new public functions, overly complex or hard-to-read constructs, and clear "
    "violations of the language's idioms. This project is Python. Do not flag "
    "purely subjective nitpicks with no real readability impact. " + _SHARED_INSTRUCTIONS
)

CORRECTNESS_SYSTEM_PROMPT = (
    "You are a senior software engineer reviewing a pull request diff for "
    "functional correctness: incorrect logic, off-by-one errors, unhandled edge "
    "cases, wrong API usage, broken control flow, and behavior that contradicts "
    "the apparent intent of the surrounding code. This is not a security or "
    "performance review — focus purely on whether the code does what it appears "
    "to intend to do. " + _SHARED_INSTRUCTIONS
)

CRITIQUE_INSTRUCTIONS = (
    "Critically re-examine the findings you just drafted against the diff above. "
    "Drop any that are false positives, speculative, not clearly supported by the "
    "diff, or out of scope for your role. Adjust severity and confidence where "
    "they're overstated or understated — be honest, not optimistic. Sharpen any "
    "recommendation that isn't concrete enough to act on directly. Do not invent "
    "new findings you didn't already report. Return the final, refined result."
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


_SEVERITY_PENALTY = {"critical": 34, "warning": 10, "suggestion": 3}
_SEVERITY_RANK = {"critical": 0, "warning": 1, "suggestion": 2}


def _compute_merge_readiness(findings: list[Finding]) -> int:
    """Deterministic 0-100 score — NOT the LLM's call. Starts at 100 and loses points
    per finding, weighted by severity and discounted by the model's own confidence
    (a low-confidence critical costs less than a high-confidence one). Floors at 0.
    """
    score = 100
    for finding in findings:
        weight = _SEVERITY_PENALTY[finding.severity] * (finding.confidence / 100)
        score -= weight
    return max(0, round(score))


def _compute_verdict(findings: list[Finding]) -> str:
    """Any high-confidence critical finding blocks the merge, full stop — this is a
    hard rule in code, not something any lens's own ``approved`` flag can override.
    A critical finding with low confidence (<50) doesn't count, since the model
    itself isn't sure it's real.
    """
    has_blocking_critical = any(
        f.severity == "critical" and f.confidence >= 50 for f in findings
    )
    return "request_changes" if has_blocking_critical else "approve"


async def aggregate_and_rank(state: ReviewState) -> dict:
    """Merge all lens outputs into one ``ReviewResult``, ranked by severity, compute
    the deterministic merge verdict/readiness score, and split out which findings
    are new vs. already reported on a prior push to this same PR (so
    ``format_output`` doesn't re-post duplicate inline comments).
    """
    lenses = [state.security, state.scalability, state.style, state.correctness]

    all_findings: list[Finding] = [finding for lens in lenses for finding in lens.findings]
    all_findings.sort(key=lambda finding: (_SEVERITY_RANK[finding.severity], -finding.confidence))

    summary_parts = [lens.summary for lens in lenses if lens.summary]
    summary = " ".join(summary_parts) or "No issues found."

    seen = await get_seen_fingerprints(state.pr_id)
    new_findings, recurring_findings = split_new_and_recurring(all_findings, seen)
    if recurring_findings:
        summary += f" ({len(recurring_findings)} previously reported finding(s) remain unresolved.)"

    verdict = _compute_verdict(all_findings)
    readiness_score = _compute_merge_readiness(all_findings)

    aggregated = ReviewResult(summary=summary, findings=all_findings, approved=verdict == "approve")
    return {
        "aggregated": aggregated,
        "new_findings": new_findings,
        "verdict": verdict,
        "merge_readiness_score": readiness_score,
    }


_SEVERITY_BADGE = {"critical": "🔴 Critical", "warning": "🟡 Warning", "suggestion": "🟢 Suggestion"}


def _format_finding_block(finding: Finding) -> str:
    return (
        f"**`{finding.file}:{finding.line}`** · {finding.category} · {finding.confidence}% confidence\n"
        f"{finding.description}\n\n"
        f"**Recommendation:** {finding.recommendation}"
    )


async def format_output(state: ReviewState) -> dict:
    """Render the aggregated result into a structured, professional GitHub review body:
    a header with the deterministic verdict/readiness score, a summary table of finding
    counts by severity, and findings grouped by severity with confidence and concrete
    recommendations — built so a developer can tell at a glance whether the PR is
    mergeable and exactly what to fix if it isn't.

    Inline comments are only posted for ``new_findings`` — recurring findings already
    have a comment from a prior review of this PR, so re-posting them on every push
    would just spam duplicate comments on the same line.
    """
    result = state.aggregated or ReviewResult()

    counts = {"critical": 0, "warning": 0, "suggestion": 0}
    for finding in result.findings:
        counts[finding.severity] += 1

    verdict_line = (
        "✅ **Ready to merge**" if state.verdict == "approve" else "⛔ **Changes requested — do not merge**"
    )

    sections = [
        f"## PR Review — {verdict_line}",
        f"**Merge readiness: {state.merge_readiness_score}%**",
        "",
        result.summary,
        "",
        "| Severity | Count |",
        "|---|---|",
        f"| 🔴 Critical | {counts['critical']} |",
        f"| 🟡 Warning | {counts['warning']} |",
        f"| 🟢 Suggestion | {counts['suggestion']} |",
    ]

    for severity in ("critical", "warning", "suggestion"):
        matching = [f for f in result.findings if f.severity == severity]
        if not matching:
            continue
        sections.append(f"\n### {_SEVERITY_BADGE[severity]} ({len(matching)})")
        for finding in matching:
            sections.append("\n" + _format_finding_block(finding))

    body = "\n".join(sections)

    comments = [
        {
            "path": finding.file,
            "line": finding.line,
            "body": (
                f"{_SEVERITY_BADGE[finding.severity]} · {finding.category} · "
                f"{finding.confidence}% confidence\n\n"
                f"{finding.description}\n\n**Recommendation:** {finding.recommendation}"
            ),
        }
        for finding in state.new_findings
    ]

    return {
        "output": {
            "event": "APPROVE" if state.verdict == "approve" else "REQUEST_CHANGES",
            "body": body,
            "comments": comments,
        }
    }
