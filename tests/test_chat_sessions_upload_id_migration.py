"""chat_sessions.upload_id column migration tests (#290)."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.migrations.chat_sessions_upload_id import (
    ensure_chat_sessions_upload_id_column,
)


@pytest.fixture
async def legacy_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE lessonplan_uploads (id INTEGER PRIMARY KEY, "
                "user_id INTEGER NOT NULL, original_filename VARCHAR(255))"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE chat_sessions (id INTEGER PRIMARY KEY, "
                "user_id INTEGER NOT NULL, title VARCHAR(255), "
                "document_id VARCHAR(512))"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO chat_sessions (id, user_id, title) "
                "VALUES (1, 1, 'a'), (2, 1, 'b')"
            )
        )
    yield engine
    await engine.dispose()


def _schema(sync_conn):
    inspector = inspect(sync_conn)
    columns = {c["name"] for c in inspector.get_columns("chat_sessions")}
    indexes = {i["name"] for i in inspector.get_indexes("chat_sessions")}
    return columns, indexes


async def _upload_ids(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT id, upload_id FROM chat_sessions ORDER BY id")
        )
        return dict(rows.all())


async def test_adds_nullable_fk_column_and_index(legacy_engine):
    added = await ensure_chat_sessions_upload_id_column(legacy_engine)

    assert added is True
    async with legacy_engine.connect() as conn:
        columns, indexes = await conn.run_sync(_schema)
        fks = (
            await conn.execute(text("PRAGMA foreign_key_list(chat_sessions)"))
        ).all()
    assert "upload_id" in columns
    assert "ix_chat_sessions_upload_id" in indexes
    # 백필 없음
    assert await _upload_ids(legacy_engine) == {1: None, 2: None}
    # PRAGMA foreign_key_list: (id, seq, table, from, to, on_update, on_delete, match)
    assert [(fk[2], fk[3], fk[4], fk[6]) for fk in fks] == [
        ("lessonplan_uploads", "upload_id", "id", "SET NULL")
    ]


async def test_second_run_is_idempotent(legacy_engine):
    await ensure_chat_sessions_upload_id_column(legacy_engine)

    assert await ensure_chat_sessions_upload_id_column(legacy_engine) is False
    assert await _upload_ids(legacy_engine) == {1: None, 2: None}


async def test_missing_table_is_skipped():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    try:
        assert await ensure_chat_sessions_upload_id_column(engine) is False
    finally:
        await engine.dispose()
