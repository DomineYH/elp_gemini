"""chat_sessions.user_type 라벨 정규화 마이그레이션 테스트"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import rename_chat_session_in_service_teacher_label


async def _create_chat_sessions_table(engine):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE chat_sessions ("
                "id INTEGER PRIMARY KEY, "
                "user_id INTEGER, "
                "title VARCHAR(255), "
                "user_type VARCHAR(50), "
                "created_at DATETIME, "
                "updated_at DATETIME)"
            )
        )


async def _insert_user_type(engine, value):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO chat_sessions (user_type) VALUES (:v)"
            ),
            {"v": value},
        )


async def _count_user_type(engine, value):
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM chat_sessions WHERE user_type = :v"
            ),
            {"v": value},
        )
        return result.scalar_one()


@pytest.mark.asyncio
async def test_renames_hyunjik_to_kyosa(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await _create_chat_sessions_table(engine)
    await _insert_user_type(engine, "현직교사")
    await _insert_user_type(engine, "현직교사")
    await _insert_user_type(engine, "1학년")

    updated = await rename_chat_session_in_service_teacher_label(engine)

    assert updated == 2
    assert await _count_user_type(engine, "현직교사") == 0
    assert await _count_user_type(engine, "교사") == 2
    assert await _count_user_type(engine, "1학년") == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await _create_chat_sessions_table(engine)
    await _insert_user_type(engine, "현직교사")

    first = await rename_chat_session_in_service_teacher_label(engine)
    second = await rename_chat_session_in_service_teacher_label(engine)

    assert first == 1
    assert second == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_no_rows_to_rename(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await _create_chat_sessions_table(engine)
    await _insert_user_type(engine, "1학년")
    await _insert_user_type(engine, "교사")

    updated = await rename_chat_session_in_service_teacher_label(engine)

    assert updated == 0
    assert await _count_user_type(engine, "1학년") == 1
    assert await _count_user_type(engine, "교사") == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_skips_when_table_missing(tmp_path):
    db_path = tmp_path / "empty.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    updated = await rename_chat_session_in_service_teacher_label(engine)

    assert updated == 0

    await engine.dispose()
