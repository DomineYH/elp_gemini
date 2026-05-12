"""display_alias 컬럼 마이그레이션 테스트"""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import ensure_criteria_display_alias_column


@pytest.mark.asyncio
async def test_adds_display_alias_when_missing(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE criteria ("
                "id INTEGER PRIMARY KEY, "
                "title VARCHAR(255) NOT NULL, "
                "document_id VARCHAR(500), "
                "file_size BIGINT NOT NULL, "
                "file_path VARCHAR(500) NOT NULL, "
                "status VARCHAR(50) NOT NULL, "
                "uploaded_by VARCHAR(255) NOT NULL, "
                "activated_at DATETIME, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "synced_at DATETIME)"
            )
        )

    patched = await ensure_criteria_display_alias_column(engine)
    assert patched is True

    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("criteria")}
        )
    assert "display_alias" in cols

    patched_again = await ensure_criteria_display_alias_column(engine)
    assert patched_again is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_skips_when_table_missing(tmp_path):
    db_path = tmp_path / "empty.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    patched = await ensure_criteria_display_alias_column(engine)
    assert patched is False
    await engine.dispose()
