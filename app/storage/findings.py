"""SQLite-backed findings history — tracks what's already been reported per PR
so subsequent pushes don't re-post duplicate inline comments for unresolved issues.
"""

from __future__ import annotations

import aiosqlite

from app.agent.schemas import Finding
from app.config import settings

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS findings (
    pr_id INTEGER NOT NULL,
    head_sha TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_findings_pr_id ON findings (pr_id)
"""


def _fingerprint(file: str, line: int, category: str) -> tuple[str, int, str]:
    """Identity of a finding across reviews: same file/line/category is the same issue."""
    return (file, line, category)


async def init_findings_db(db_path: str | None = None) -> None:
    """Create the ``findings`` table (and its index) if they don't exist yet."""
    async with aiosqlite.connect(db_path or settings.db_path) as db:
        await db.execute(_CREATE_TABLE)
        await db.execute(_CREATE_INDEX)
        await db.commit()


async def get_seen_fingerprints(pr_id: int, db_path: str | None = None) -> set[tuple[str, int, str]]:
    """Return (file, line, category) fingerprints already reported on any prior review of this PR."""
    async with aiosqlite.connect(db_path or settings.db_path) as db:
        cursor = await db.execute(
            "SELECT DISTINCT file, line, category FROM findings WHERE pr_id = ?",
            (pr_id,),
        )
        rows = await cursor.fetchall()
        return {(file, line, category) for file, line, category in rows}


async def save_findings(pr_id: int, head_sha: str, findings: list[Finding], db_path: str | None = None) -> None:
    """Persist this review's findings, so future pushes to the same PR can detect recurrences."""
    if not findings:
        return

    async with aiosqlite.connect(db_path or settings.db_path) as db:
        await db.executemany(
            """
            INSERT INTO findings (pr_id, head_sha, file, line, category, severity, description, recommendation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (pr_id, head_sha, f.file, f.line, f.category, f.severity, f.description, f.recommendation)
                for f in findings
            ],
        )
        await db.commit()


def split_new_and_recurring(
    findings: list[Finding], seen: set[tuple[str, int, str]]
) -> tuple[list[Finding], list[Finding]]:
    """Partition findings into (new, recurring) based on previously seen fingerprints."""
    new_findings, recurring_findings = [], []
    for finding in findings:
        target = recurring_findings if _fingerprint(finding.file, finding.line, finding.category) in seen else new_findings
        target.append(finding)
    return new_findings, recurring_findings
