from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


from app.migrations.criteria_schema import (
    ensure_criteria_file_path_column,
)


def _create_legacy_criteria_table(db_path: Path, with_file_path: bool):
    """Helper to create criteria table with optional file_path column."""
    ddl_parts = [
        "id INTEGER PRIMARY KEY",
        "title VARCHAR(255) NOT NULL",
        "document_id VARCHAR(500)",
        "file_size BIGINT NOT NULL",
        "status VARCHAR(50) NOT NULL",
        "uploaded_by VARCHAR(255) NOT NULL",
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    ]
    if with_file_path:
        ddl_parts.insert(
            4,
            "file_path VARCHAR(500) NOT NULL DEFAULT 'temp_path'",
        )

    sync_engine = create_engine(f"sqlite:///{db_path}")
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE criteria ({', '.join(ddl_parts)})"
            )
        )
        if with_file_path:
            conn.execute(
                text(
                    "INSERT INTO criteria "
                    "(title, document_id, file_size, file_path, "
                    "status, uploaded_by) "
                    "VALUES "
                    "('existing.pdf', NULL, 128, '/tmp/existing.pdf', "
                    "'uploaded', 'admin')"
                )
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO criteria "
                    "(title, document_id, file_size, status, uploaded_by) "
                    "VALUES "
                    "('legacy.pdf', NULL, 256, 'uploaded', 'admin')"
                )
            )


@pytest.mark.asyncio
async def test_schema_patch_adds_missing_file_path(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_criteria_table(db_path, with_file_path=False)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        applied = await ensure_criteria_file_path_column(engine)
        assert applied is True

        async with engine.begin() as conn:
            columns = await conn.run_sync(
                lambda sync_conn: inspect(
                    sync_conn
                ).get_columns("criteria")
            )
            column_names = [col["name"] for col in columns]
            assert "file_path" in column_names

            result = await conn.execute(
                text("SELECT file_path FROM criteria LIMIT 1")
            )
            file_path = result.scalar_one()
            assert file_path == "legacy_missing"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_schema_patch_is_idempotent(tmp_path):
    db_path = tmp_path / "modern.db"
    _create_legacy_criteria_table(db_path, with_file_path=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        applied = await ensure_criteria_file_path_column(engine)
        assert applied is False

        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT file_path FROM criteria LIMIT 1")
            )
            assert result.scalar_one() == "/tmp/existing.pdf"
    finally:
        await engine.dispose()

