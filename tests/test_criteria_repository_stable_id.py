"""CriteriaRepository stable_id helpers."""

from datetime import datetime

import pytest

from app.models.criteria import Criteria
from app.repositories.criteria_repository import CriteriaRepository


class _ScalarResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _RecordingDb:
    def __init__(self, row=None):
        self.result = _ScalarResult(row)
        self.executed = []
        self.flushed = False
        self.added = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        return self.result

    async def flush(self):
        self.flushed = True

    def add(self, row):
        self.added.append(row)


@pytest.mark.asyncio
async def test_get_by_stable_id_returns_row():
    expected = Criteria(
        title="t.pdf",
        document_id="d1",
        file_size=10,
        file_path="x",
        status="uploaded",
        uploaded_by="admin",
        stable_id="01HSID",
    )
    repo = CriteriaRepository(_RecordingDb(row=expected))

    row = await repo.get_criteria_by_stable_id("01HSID")

    assert row is expected


@pytest.mark.asyncio
async def test_get_by_stable_id_returns_none_for_missing():
    repo = CriteriaRepository(_RecordingDb(row=None))

    assert await repo.get_criteria_by_stable_id("nope") is None


@pytest.mark.asyncio
async def test_truncate_executes_delete_and_flushes():
    db = _RecordingDb()
    repo = CriteriaRepository(db)

    await repo.truncate()

    assert db.executed
    assert db.flushed is True


@pytest.mark.asyncio
async def test_insert_persists_activated_at():
    db = _RecordingDb()
    repo = CriteriaRepository(db)

    await repo.insert(
        stable_id="01HACTIVE",
        document_id="doc-active",
        title="active.pdf",
        display_alias=None,
        status="active",
        created_at="2026-05-15T03:20:00Z",
        activated_at="2026-05-15T03:21:00Z",
    )

    assert len(db.added) == 1
    row = db.added[0]
    assert isinstance(row.activated_at, datetime)
