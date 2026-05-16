"""criteria.stable_id column migration tests."""

import pytest

from app.migrations.criteria_stable_id import ensure_criteria_stable_id_column


class _FakeConn:
    def __init__(self, columns):
        self.columns = columns
        self.statements = []

    async def run_sync(self, _fn):
        return self.columns

    async def execute(self, stmt, *_args, **_kwargs):
        self.statements.append(str(stmt))


class _FakeBegin:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_exc):
        return False


class _FakeEngine:
    def __init__(self, columns):
        self.conn = _FakeConn(columns)

    def begin(self):
        return _FakeBegin(self.conn)


@pytest.mark.asyncio
async def test_adds_stable_id_when_missing():
    engine = _FakeEngine(columns={"id", "title", "display_alias"})

    added = await ensure_criteria_stable_id_column(engine)

    assert added is True
    assert any("ADD COLUMN stable_id" in s for s in engine.conn.statements)


@pytest.mark.asyncio
async def test_does_not_add_column_when_column_present_but_still_ensures_index():
    engine = _FakeEngine(columns={"id", "stable_id"})

    added = await ensure_criteria_stable_id_column(engine)

    assert added is False
    assert not any("ADD COLUMN stable_id" in s for s in engine.conn.statements)
    assert any(
        "CREATE INDEX IF NOT EXISTS idx_criteria_stable_id" in s
        for s in engine.conn.statements
    )


@pytest.mark.asyncio
async def test_creates_index_for_stable_id():
    engine = _FakeEngine(columns={"id", "title"})

    await ensure_criteria_stable_id_column(engine)

    assert any(
        "CREATE INDEX IF NOT EXISTS idx_criteria_stable_id" in s
        for s in engine.conn.statements
    )
