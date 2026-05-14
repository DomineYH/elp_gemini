"""LessonPlanUpload 모델 및 마이그레이션 idempotency 테스트."""
import pytest
import pytest_asyncio
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db import Base
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from app.models.analysis_reports import AnalysisReport
from app.migrations.lessonplan_uploads_table import (
    ensure_lessonplan_uploads_table,
)


@pytest_asyncio.fixture
async def engine(tmp_path):
    db_path = tmp_path / "test.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_upload_row_can_be_inserted_and_linked_to_report(engine):
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as s:
        user = User(
            username="alice", nickname="alice",
            email="a@a.com", hashed_password="x",
        )
        s.add(user)
        await s.flush()

        up = LessonPlanUpload(
            user_id=user.id,
            filename="alice_plan.pdf",
            original_filename="plan.pdf",
            file_hash="a" * 64,
        )
        s.add(up)
        await s.flush()

        report = AnalysisReport(
            user_id=user.id,
            lessonplan_filename="alice_plan.pdf",
            lessonplan_original_name="plan.pdf",
            report_filename="r.md",
            report_path="/tmp/r.md",
            upload_id=up.id,
        )
        s.add(report)
        await s.commit()

        # Round-trip
        row = (
            await s.execute(
                select(AnalysisReport).where(
                    AnalysisReport.upload_id == up.id
                )
            )
        ).scalar_one()
        assert row.upload_id == up.id


@pytest.mark.asyncio
async def test_ensure_lessonplan_uploads_table_tolerates_fresh_db(
    tmp_path
):
    """Migration should tolerate running before ORM tables exist."""
    db_path = tmp_path / "fresh.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    added = await ensure_lessonplan_uploads_table(eng)

    assert added is True

    def _tables(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    async with eng.begin() as conn:
        tables = await conn.run_sync(_tables)
    assert "lessonplan_uploads" in tables
    assert "users" not in tables
    assert "analysis_reports" not in tables
    await eng.dispose()


@pytest.mark.asyncio
async def test_ensure_lessonplan_uploads_table_is_idempotent(tmp_path):
    """Migration should be safe to run twice and leave the schema valid."""
    db_path = tmp_path / "idempotent.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    # Build the rest of the schema first (users + analysis_reports baseline)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    added1 = await ensure_lessonplan_uploads_table(eng)
    added2 = await ensure_lessonplan_uploads_table(eng)

    # Either may report True the first time (depending on whether
    # Base.metadata.create_all already covered the new table), but
    # the second call must be a no-op (returns False).
    assert added2 is False

    def _columns(sync_conn):
        return {c["name"] for c in inspect(sync_conn).get_columns(
            "analysis_reports"
        )}

    def _upload_indexes(sync_conn):
        return {ix["name"] for ix in inspect(sync_conn).get_indexes(
            "lessonplan_uploads"
        )}

    async with eng.begin() as conn:
        cols = await conn.run_sync(_columns)
        upload_indexes = await conn.run_sync(_upload_indexes)
    assert "upload_id" in cols
    assert (
        "uq_lessonplan_uploads_synthetic_per_user" in upload_indexes
    )
    await eng.dispose()


@pytest.mark.asyncio
async def test_ensure_lessonplan_uploads_table_does_not_backfill_legacy_reports(
    tmp_path
):
    db_path = tmp_path / "legacy.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async with eng.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(255) NOT NULL UNIQUE,
                nickname VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE,
                hashed_password VARCHAR(255),
                is_admin BOOLEAN NOT NULL DEFAULT 0,
                failed_login_count INTEGER NOT NULL DEFAULT 0,
                locked_until DATETIME,
                last_failed_login_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE analysis_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                lessonplan_filename VARCHAR(500) NOT NULL,
                lessonplan_original_name VARCHAR(500),
                report_filename VARCHAR(500) NOT NULL,
                report_path VARCHAR(1000) NOT NULL,
                latency_ms INTEGER,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            INSERT INTO users (
                username, nickname, email, hashed_password
            )
            VALUES ('alice', 'alice', 'a@a.com', 'x')
        """))
        await conn.execute(text("""
            INSERT INTO analysis_reports (
                user_id, lessonplan_filename, lessonplan_original_name,
                report_filename, report_path, latency_ms, created_at
            )
            VALUES (
                1, 'alice_plan.pdf', 'plan.pdf', 'report.md',
                '/tmp/report.md', 123, '2026-05-13 12:34:56'
            )
        """))

    added = await ensure_lessonplan_uploads_table(eng)
    added_again = await ensure_lessonplan_uploads_table(eng)

    assert added is True
    assert added_again is False

    async with eng.begin() as conn:
        upload_count = (
            await conn.execute(text(
                "SELECT COUNT(*) FROM lessonplan_uploads"
            ))
        ).scalar_one()
        report = (
            await conn.execute(text(
                "SELECT id, upload_id FROM analysis_reports"
            ))
        ).mappings().one()

    assert upload_count == 0
    assert report["upload_id"] is None
    await eng.dispose()
