"""users.survey_completed_at 컬럼 보정 마이그레이션 검증 (issue: 설문 게이트)."""
import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.migrations.users_survey_completed_column import (
    ensure_users_survey_completed_column,
)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # survey_completed_at 없는 구버전 users 테이블 생성
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, "
                "username TEXT NOT NULL, "
                "nickname TEXT NOT NULL, "
                "hashed_password TEXT, "
                "is_admin BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
    yield eng
    await eng.dispose()


def _columns(sync_conn):
    return {c["name"] for c in inspect(sync_conn).get_columns("users")}


@pytest.mark.asyncio
async def test_adds_survey_completed_at_column(engine):
    added = await ensure_users_survey_completed_column(engine)
    assert added is True
    async with engine.begin() as conn:
        cols = await conn.run_sync(_columns)
    assert "survey_completed_at" in cols


@pytest.mark.asyncio
async def test_idempotent(engine):
    await ensure_users_survey_completed_column(engine)
    again = await ensure_users_survey_completed_column(engine)
    assert again is False
