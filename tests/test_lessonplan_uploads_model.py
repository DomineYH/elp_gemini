"""LessonPlanUpload 모델 및 마이그레이션 idempotency 테스트."""
import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
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

    async with eng.begin() as conn:
        cols = await conn.run_sync(_columns)
    assert "upload_id" in cols
    await eng.dispose()
