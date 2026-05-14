"""LessonPlanAnalysisService 중복 분석 차단 동작 테스트."""
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.exc import IntegrityError

from app.db import Base
from app.models.users import User
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.analysis_reports import AnalysisReport
from app.services.lessonplan_analysis_service import (
    LessonPlanAnalysisService,
)


@pytest_asyncio.fixture
async def session(tmp_path):
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/t.db"
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        yield s
    await eng.dispose()


async def _seed_user_and_upload(s):
    u = User(
        username="alice", nickname="alice",
        email="a@a.com", hashed_password="x",
    )
    s.add(u)
    await s.flush()
    up = LessonPlanUpload(
        user_id=u.id,
        filename="alice_plan.pdf",
        original_filename="plan.pdf",
        file_hash="a" * 64,
    )
    s.add(up)
    await s.flush()
    await s.commit()
    return u, up


@pytest.mark.asyncio
async def test_analyze_blocks_when_upload_already_analyzed(session):
    u, up = await _seed_user_and_upload(session)
    existing = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=up.filename,
        lessonplan_original_name=up.original_filename,
        report_filename="r.md",
        report_path="/tmp/r.md",
        upload_id=up.id,
    )
    session.add(existing)
    await session.commit()

    svc = LessonPlanAnalysisService(db=session)

    # Gemini client must NOT be called
    with patch.object(
        svc, "_get_store_ids"
    ) as mock_stores, patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search"
    ) as mock_gemini:
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id, username=u.username,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == existing.id
    assert mock_stores.call_count == 0
    assert mock_gemini.call_count == 0


@pytest.mark.asyncio
async def test_analyze_proceeds_when_no_existing_report(session):
    u, up = await _seed_user_and_upload(session)
    svc = LessonPlanAnalysisService(db=session)

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    with patch.object(
        svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.lessonplan_storage, "list_lessonplans",
        return_value=[{
            "filename": up.filename,
            "original_filename": up.original_filename,
            "created_at": "2026-05-13T00:00:00",
        }],
    ), patch.object(
        svc.report_storage, "save_report",
        return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id, username=u.username,
        )

    assert result["success"] is True

    saved = (
        await session.execute(
            select(AnalysisReport).where(AnalysisReport.upload_id == up.id)
        )
    ).scalar_one()
    assert saved.upload_id == up.id


@pytest.mark.asyncio
async def test_analyze_race_fallback_on_integrity_error(session):
    u, up = await _seed_user_and_upload(session)

    # Pre-existing report — simulates "other request finished first"
    winner = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=up.filename,
        lessonplan_original_name=up.original_filename,
        report_filename="r.md",
        report_path="/tmp/r.md",
        upload_id=up.id,
    )
    session.add(winner)
    await session.commit()

    svc = LessonPlanAnalysisService(db=session)

    # Force the dedup pre-check to MISS (simulate a TOCTOU race) by
    # patching the inner query to return None just for this call.
    # Then the INSERT below will hit IntegrityError, which should
    # be caught and converted to ALREADY_ANALYZED.
    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    real_find = svc._find_existing_report_for_latest_upload

    call_count = {"n": 0}

    async def racing_find(username):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call (pre-flight) — pretend nothing is there yet
            return (up, None)
        # Second call (after IntegrityError) — real lookup finds winner
        return await real_find(username)

    with patch.object(
        svc, "_find_existing_report_for_latest_upload",
        side_effect=racing_find,
    ), patch.object(
        svc, "_get_store_ids", return_value=["u", "r"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.lessonplan_storage, "list_lessonplans",
        return_value=[{
            "filename": up.filename,
            "original_filename": up.original_filename,
            "created_at": "2026-05-13T00:00:00",
        }],
    ), patch.object(
        svc.report_storage, "save_report",
        return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id, username=u.username,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id


@pytest.mark.asyncio
async def test_analyze_race_fallback_does_not_delete_winner_when_paths_collide(
    session, tmp_path
):
    u, up = await _seed_user_and_upload(session)

    winner_path = tmp_path / "winner.md"
    winner_path.write_text("# Existing report\n", encoding="utf-8")

    winner = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=up.filename,
        lessonplan_original_name=up.original_filename,
        report_filename=winner_path.name,
        report_path=str(winner_path),
        upload_id=up.id,
    )
    session.add(winner)
    await session.commit()

    svc = LessonPlanAnalysisService(db=session)

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    real_find = svc._find_existing_report_for_latest_upload
    call_count = {"n": 0}

    async def racing_find(username):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (up, None)
        return await real_find(username)

    with patch.object(
        svc,
        "_find_existing_report_for_latest_upload",
        side_effect=racing_find,
    ), patch.object(
        svc, "_get_store_ids", return_value=["u", "r"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.lessonplan_storage, "list_lessonplans",
        return_value=[{
            "filename": up.filename,
            "original_filename": up.original_filename,
            "created_at": "2026-05-13T00:00:00",
        }],
    ), patch.object(
        svc.report_storage,
        "save_report",
        return_value={
            "filename": winner_path.name,
            "file_path": str(winner_path),
        },
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id, username=u.username,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id
    assert winner_path.exists()


@pytest.mark.asyncio
async def test_analyze_race_fallback_cleans_up_orphan_report(
    session, tmp_path
):
    u, up = await _seed_user_and_upload(session)

    winner = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=up.filename,
        lessonplan_original_name=up.original_filename,
        report_filename="winner.md",
        report_path="/tmp/winner.md",
        upload_id=up.id,
    )
    session.add(winner)
    await session.commit()

    svc = LessonPlanAnalysisService(db=session)

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    real_find = svc._find_existing_report_for_latest_upload
    call_count = {"n": 0}

    async def racing_find(username):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (up, None)
        return await real_find(username)

    orphan_path = tmp_path / "orphan.md"

    def save_orphan_report(**kwargs):
        orphan_path.write_text(kwargs["report_content"], encoding="utf-8")
        return {
            "filename": orphan_path.name,
            "file_path": str(orphan_path),
        }

    with patch.object(
        svc,
        "_find_existing_report_for_latest_upload",
        side_effect=racing_find,
    ), patch.object(
        svc, "_get_store_ids", return_value=["u", "r"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.lessonplan_storage, "list_lessonplans",
        return_value=[{
            "filename": up.filename,
            "original_filename": up.original_filename,
            "created_at": "2026-05-13T00:00:00",
        }],
    ), patch.object(
        svc.report_storage, "save_report", side_effect=save_orphan_report,
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id, username=u.username,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id
    assert not orphan_path.exists()
