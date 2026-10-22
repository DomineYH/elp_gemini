"""chat_sessions.document_id column migration tests (#175)."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.migrations.chat_sessions_document_id import (
    ensure_chat_sessions_document_id_column,
)

PATH = "fileSearchStores/s1/documents/d1"
PATH2 = "fileSearchStores/s1/documents/d2"
TITLES = {1: "lesson.pdf", 2: "내 수업", 3: "업로드한 지도안"}


@pytest.fixture
async def legacy_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE chat_sessions (id INTEGER PRIMARY KEY, "
                "user_id INTEGER NOT NULL, title VARCHAR(255))"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO chat_sessions (id, user_id, title) "
                f"VALUES (1, 1, '{PATH}'), (2, 1, '내 수업'), "
                f"(3, 2, '{PATH2}')"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE lessonplan_uploads (id INTEGER PRIMARY KEY, "
                "user_id INTEGER NOT NULL, original_filename VARCHAR(255), "
                "fs_document_id VARCHAR(512), created_at DATETIME)"
            )
        )
        # 최신 업로드 우선, 빈 파일명 제외, 다른 사용자의 업로드는 매칭 안 함
        await conn.execute(
            text(
                "INSERT INTO lessonplan_uploads "
                "(id, user_id, original_filename, fs_document_id, created_at) "
                f"VALUES (1, 1, 'old.pdf', '{PATH}', '2026-01-01'), "
                f"(2, 1, 'lesson.pdf', '{PATH}', '2026-02-01'), "
                f"(3, 1, NULL, '{PATH}', '2026-03-01'), "
                f"(4, 1, 'other.pdf', '{PATH2}', '2026-03-01')"
            )
        )
    yield engine
    await engine.dispose()


def _schema(sync_conn):
    inspector = inspect(sync_conn)
    columns = {c["name"] for c in inspector.get_columns("chat_sessions")}
    indexes = {i["name"] for i in inspector.get_indexes("chat_sessions")}
    return columns, indexes


async def _document_ids(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT id, document_id FROM chat_sessions ORDER BY id")
        )
        return dict(rows.all())


async def _titles(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT id, title FROM chat_sessions ORDER BY id")
        )
        return dict(rows.all())


async def test_adds_column_index_and_backfills_path_titles(legacy_engine):
    added = await ensure_chat_sessions_document_id_column(legacy_engine)

    assert added is True
    async with legacy_engine.connect() as conn:
        columns, indexes = await conn.run_sync(_schema)
    assert "document_id" in columns
    assert "idx_chat_sessions_document_id" in indexes
    assert await _document_ids(legacy_engine) == {
        1: PATH,
        2: None,
        3: PATH2,
    }
    assert await _titles(legacy_engine) == TITLES


async def test_second_run_is_idempotent(legacy_engine, caplog):
    await ensure_chat_sessions_document_id_column(legacy_engine)

    caplog.clear()
    with caplog.at_level(
        "INFO", logger="app.migrations.chat_sessions_document_id"
    ):
        added = await ensure_chat_sessions_document_id_column(legacy_engine)

    assert added is False
    # 두 UPDATE 모두 rowcount == 0이면 로그가 남지 않는다
    assert "백필" not in caplog.text
    assert "레거시 제목" not in caplog.text
    assert await _document_ids(legacy_engine) == {
        1: PATH,
        2: None,
        3: PATH2,
    }
    assert await _titles(legacy_engine) == TITLES


async def test_missing_table_is_skipped():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    try:
        assert await ensure_chat_sessions_document_id_column(engine) is False
    finally:
        await engine.dispose()


async def test_long_upload_filename_is_truncated_to_title_length(
    legacy_engine,
):
    long_name = "가" * 300 + ".pdf"
    path3 = "fileSearchStores/s1/documents/d3"
    async with legacy_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO chat_sessions (id, user_id, title) "
                f"VALUES (4, 3, '{path3}')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO lessonplan_uploads "
                "(id, user_id, original_filename, fs_document_id, created_at) "
                f"VALUES (5, 3, '{long_name}', '{path3}', '2026-01-01')"
            )
        )

    await ensure_chat_sessions_document_id_column(legacy_engine)

    title = (await _titles(legacy_engine))[4]
    assert len(title) == 255
    assert title == long_name[:255]
