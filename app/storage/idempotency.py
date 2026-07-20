"""SQLite-backed idempotency store — avoids re-reviewing a PR at the same head_sha."""

from __future__ import annotations

import aiosqlite

from app.config import settings

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS processed_reviews (
    pr_id INTEGER NOT NULL,
    head_sha TEXT NOT NULL,
    review_id INTEGER NOT NULL,
    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (pr_id, head_sha)
)
"""


async def init_db(db_path: str | None = None) -> None:
    """Create the ``processed_reviews`` table if it doesn't exist yet."""
    async with aiosqlite.connect(db_path or settings.db_path) as db:
        await db.execute(_CREATE_TABLE)
        await db.commit()


async def is_processed(pr_id: int, head_sha: str, db_path: str | None = None) -> bool:
    """Return True if this exact (pr_id, head_sha) pair was already reviewed."""
    async with aiosqlite.connect(db_path or settings.db_path) as db:
        cursor = await db.execute(
            "SELECT 1 FROM processed_reviews WHERE pr_id = ? AND head_sha = ?",
            (pr_id, head_sha),
        )
        row = await cursor.fetchone()
        return row is not None


async def mark_processed(pr_id: int, head_sha: str, review_id: int, db_path: str | None = None) -> None:
    """Record that (pr_id, head_sha) has been reviewed as ``review_id``.

    Idempotent: re-marking the same (pr_id, head_sha) overwrites the stored
    review_id rather than raising a primary-key conflict.
    """
    async with aiosqlite.connect(db_path or settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO processed_reviews (pr_id, head_sha, review_id)
            VALUES (?, ?, ?)
            ON CONFLICT (pr_id, head_sha) DO UPDATE SET review_id = excluded.review_id
            """,
            (pr_id, head_sha, review_id),
        )
        await db.commit()
