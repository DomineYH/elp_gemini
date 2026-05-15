# tests/unit/test_app_state_repository.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_API_KEY_HASH,
    KEY_SYNC_STATE,
)


@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def repo(mock_db):
    return AppStateRepository(db=mock_db)


@pytest.mark.asyncio
async def test_get_returns_none_when_key_missing(repo, mock_db):
    result = AsyncMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    assert await repo.get("nonexistent") is None


@pytest.mark.asyncio
async def test_set_inserts_or_updates(repo, mock_db):
    result = AsyncMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    await repo.set(KEY_SYNC_STATE, "ok")
    mock_db.add.assert_called_once()
    mock_db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_set_many_persists_all_keys(repo, mock_db):
    result = AsyncMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    await repo.set_many({KEY_API_KEY_HASH: "abc", KEY_SYNC_STATE: "ok"})
    assert mock_db.add.call_count == 2
