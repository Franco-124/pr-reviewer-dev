import pytest
import pytest_asyncio

from app.storage.idempotency import init_db, is_processed, mark_processed


@pytest_asyncio.fixture
async def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path


@pytest.mark.asyncio
async def test_is_processed_false_when_unseen(db_path):
    assert await is_processed(1, "abc123", db_path) is False


@pytest.mark.asyncio
async def test_mark_then_is_processed_true(db_path):
    await mark_processed(1, "abc123", review_id=999, db_path=db_path)
    assert await is_processed(1, "abc123", db_path) is True


@pytest.mark.asyncio
async def test_different_head_sha_not_processed(db_path):
    await mark_processed(1, "abc123", review_id=999, db_path=db_path)
    assert await is_processed(1, "def456", db_path) is False


@pytest.mark.asyncio
async def test_remark_overwrites_review_id(db_path):
    await mark_processed(1, "abc123", review_id=999, db_path=db_path)
    await mark_processed(1, "abc123", review_id=1000, db_path=db_path)
    assert await is_processed(1, "abc123", db_path) is True
