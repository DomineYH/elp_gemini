"""CriteriaRepository alias method tests."""

import pytest

from app.models.criteria import Criteria
from app.repositories.criteria_repository import CriteriaRepository


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._row

    def scalars(self):
        return _Scalars(self._rows)


class _Db:
    def __init__(self, *, row=None, rows=None):
        self.result = _Result(row=row, rows=rows)
        self.flushed = False
        self.refreshed = []
        self.executed = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        return self.result

    async def flush(self):
        self.flushed = True

    async def refresh(self, row):
        self.refreshed.append(row)


@pytest.mark.asyncio
async def test_update_display_alias_sets_value():
    criteria = Criteria(
        id=1,
        title="test.pdf",
        file_size=100,
        uploaded_by="admin",
        file_path="/tmp/test.pdf",
    )
    db = _Db(row=criteria)
    repo = CriteriaRepository(db)

    updated = await repo.update_display_alias(criteria.id, "수학 평가기준")

    assert updated is criteria
    assert updated.display_alias == "수학 평가기준"
    assert db.flushed is True
    assert db.refreshed == [criteria]


@pytest.mark.asyncio
async def test_update_display_alias_returns_none_for_missing():
    repo = CriteriaRepository(_Db(row=None))

    result = await repo.update_display_alias(9999, "없는 값")

    assert result is None


@pytest.mark.asyncio
async def test_get_criteria_map_by_document_ids():
    c1 = Criteria(
        id=1,
        title="a.pdf",
        file_size=1,
        uploaded_by="admin",
        file_path="/tmp/a.pdf",
        document_id="doc-aaa",
        status="active",
    )
    c2 = Criteria(
        id=2,
        title="b.pdf",
        file_size=1,
        uploaded_by="admin",
        file_path="/tmp/b.pdf",
        document_id="doc-bbb",
        status="active",
    )
    repo = CriteriaRepository(_Db(rows=[c1, c2]))

    mapping = await repo.get_criteria_map_by_document_ids([
        "doc-aaa",
        "doc-bbb",
        "doc-missing",
    ])

    assert mapping["doc-aaa"] is c1
    assert mapping["doc-aaa"].display_alias is None
    assert mapping["doc-bbb"] is c2
    assert "doc-missing" not in mapping


@pytest.mark.asyncio
async def test_get_criteria_map_skips_unknown_ids():
    repo = CriteriaRepository(_Db(rows=[]))

    mapping = await repo.get_criteria_map_by_document_ids(["doc-unknown"])

    assert mapping == {}
