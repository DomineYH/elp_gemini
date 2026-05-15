"""criteria.stable_id 컬럼 추가 마이그레이션 테스트"""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.migrations.criteria_stable_id import ensure_criteria_stable_id_column


@pytest.mark.asyncio
async def test_adds_stable_id_when_missing():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE criteria (
                id INTEGER PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                document_id VARCHAR(500),
                file_size BIGINT NOT NULL DEFAULT 0,
                file_path VARCHAR(500) NOT NULL DEFAULT '',
                status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
                uploaded_by VARCHAR(255) NOT NULL DEFAULT '',
                display_alias VARCHAR(255)
            )
        """))

    added = await ensure_criteria_stable_id_column(engine)
    assert added is True

    def _columns(sync_conn):
        return {c["name"] for c in inspect(sync_conn).get_columns("criteria")}

    async with engine.begin() as conn:
        cols = await conn.run_sync(_columns)
    assert "stable_id" in cols


@pytest.mark.asyncio
async def test_idempotent_when_column_present():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE criteria (
                id INTEGER PRIMARY KEY,
                stable_id VARCHAR(64)
            )
        """))

    added = await ensure_criteria_stable_id_column(engine)
    assert added is False


@pytest.mark.asyncio
async def test_creates_index_for_stable_id():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE criteria (
                id INTEGER PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                file_size BIGINT NOT NULL DEFAULT 0,
                file_path VARCHAR(500) NOT NULL DEFAULT '',
                status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
                uploaded_by VARCHAR(255) NOT NULL DEFAULT ''
            )
        """))

    await ensure_criteria_stable_id_column(engine)

    def _indexes(sync_conn):
        return {i["name"] for i in inspect(sync_conn).get_indexes("criteria")}

    async with engine.begin() as conn:
        idx = await conn.run_sync(_indexes)
    assert "idx_criteria_stable_id" in idx
