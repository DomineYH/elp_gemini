"""display_alias column migration tests."""

import pytest

from app.migrations import ensure_criteria_display_alias_column


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
async def test_adds_display_alias_when_missing():
    engine = _FakeEngine(columns={"id", "title"})

    patched = await ensure_criteria_display_alias_column(engine)

    assert patched is True
    assert any("ADD COLUMN display_alias" in s for s in engine.conn.statements)


@pytest.mark.asyncio
async def test_idempotent_when_display_alias_exists():
    engine = _FakeEngine(columns={"id", "title", "display_alias"})

    patched = await ensure_criteria_display_alias_column(engine)

    assert patched is False
    assert engine.conn.statements == []


@pytest.mark.asyncio
async def test_skips_when_table_missing():
    engine = _FakeEngine(columns=None)

    patched = await ensure_criteria_display_alias_column(engine)

    assert patched is False
    assert engine.conn.statements == []
