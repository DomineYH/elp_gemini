"""LessonPlanAnalysisService 중복 분석 차단 동작 테스트."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models.analysis_reports import AnalysisReport
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from app.services.lessonplan_analysis_service import (
    LessonPlanAnalysisService,
)
from app.services.report_storage_service import ReportStorageService


@pytest.fixture(autouse=True)
def gemini_client():
    with patch(
        "app.services.lessonplan_analysis_service.genai.Client",
        return_value=MagicMock(),
    ):
        yield


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
        hashed_password="x",
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
async def test_analyze_blocks_when_upload_already_analyzed(session, tmp_path):
    u, up = await _seed_user_and_upload(session)
    report_path = tmp_path / "r.md"
    report_path.write_text("# Existing report\n", encoding="utf-8")
    existing = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=up.filename,
        lessonplan_original_name=up.original_filename,
        report_filename="r.md",
        report_path=str(report_path),
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
            session_id=1, user_id=u.id,
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
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
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
            session_id=1, user_id=u.id,
        )

    assert result["success"] is True

    saved = (
        await session.execute(
            select(AnalysisReport).where(AnalysisReport.upload_id == up.id)
        )
    ).scalar_one()
    assert saved.upload_id == up.id


@pytest.mark.asyncio
async def test_analyze_returns_upload_required_when_no_upload_or_legacy_file(
    tmp_path
):
    lessonplan_dir = tmp_path / "lessonplans"
    lessonplan_dir.mkdir()

    db = MagicMock()
    svc = LessonPlanAnalysisService(db=db)
    svc.lessonplan_storage.base_dir = lessonplan_dir

    with patch.object(
        svc,
        "_find_existing_report_for_latest_upload",
        return_value=(None, None),
    ) as mock_existing, patch.object(
        svc.lessonplan_storage,
        "list_lessonplans",
        return_value=[],
    ) as mock_lessonplans, patch.object(
        svc, "_get_store_ids"
    ) as mock_stores, patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search"
    ) as mock_gemini:
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=1,
        )

    assert result == {
        "success": False,
        "error": "분석할 문서가 없습니다. 수업 지도안을 먼저 업로드해주세요.",
    }
    mock_existing.assert_called_once_with(1)
    mock_lessonplans.assert_called_once_with(1)
    assert mock_stores.call_count == 0
    assert mock_gemini.call_count == 0
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_allows_premigration_file_search_upload_without_row(
    tmp_path
):
    lessonplan_dir = tmp_path / "lessonplans"
    lessonplan_dir.mkdir()

    db = MagicMock()
    svc = LessonPlanAnalysisService(db=db)
    svc.lessonplan_storage.base_dir = lessonplan_dir

    store = MagicMock()
    store.display_name = "user-1-store"
    store.name = "fileSearchStores/user-store"
    doc = MagicMock()
    doc.name = "fileSearchStores/user-store/documents/doc1"
    doc.display_name = "premigration.pdf"

    svc.file_search_service.client.file_search_stores.list = MagicMock(
        return_value=[store]
    )
    svc.file_search_service.client.file_search_stores.list_documents = (
        MagicMock(return_value=[doc])
    )

    fake_response = MagicMock()
    fake_response.text = ""
    fake_response.candidates = []

    with patch.object(
        svc,
        "_find_existing_report_for_latest_upload",
        return_value=(None, None),
    ), patch.object(
        svc.lessonplan_storage,
        "list_lessonplans",
        return_value=[],
    ), patch.object(
        svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
    ) as mock_stores, patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
    ), patch(
        "app.services.lessonplan_analysis_service.asyncio.to_thread",
        return_value=fake_response,
    ) as mock_to_thread:
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=1,
        )

    assert result["success"] is True
    assert "upload" not in result.get("error", "").lower()
    mock_stores.assert_called_once_with(1)
    assert mock_to_thread.call_count == 1


@pytest.mark.asyncio
async def test_analyze_falls_through_when_existing_report_file_missing(
    session, tmp_path
):
    u, up = await _seed_user_and_upload(session)
    missing_report_path = tmp_path / "missing_report.md"
    stale = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=up.filename,
        lessonplan_original_name=up.original_filename,
        report_filename=missing_report_path.name,
        report_path=str(missing_report_path),
        upload_id=up.id,
    )
    session.add(stale)
    await session.commit()
    upload_id = up.id

    svc = LessonPlanAnalysisService(db=session)

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    saved_report_path = tmp_path / "saved_report.md"

    def save_report(**kwargs):
        saved_report_path.write_text(
            kwargs["report_content"], encoding="utf-8"
        )
        return {
            "filename": saved_report_path.name,
            "file_path": str(saved_report_path),
        }

    with patch.object(
        svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ) as mock_gemini, patch.object(
        svc.report_storage, "save_report", side_effect=save_report,
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id,
        )

    assert result["success"] is True
    assert mock_gemini.call_count == 1

    stale_row = (
        await session.execute(
            select(AnalysisReport).where(
                AnalysisReport.report_path == str(missing_report_path)
            )
        )
    ).scalar_one_or_none()
    assert stale_row is None

    saved = (
        await session.execute(
            select(AnalysisReport).where(
                AnalysisReport.report_path == str(saved_report_path)
            )
        )
    ).scalar_one()
    assert saved.upload_id == upload_id


@pytest.mark.asyncio
async def test_analyze_uses_upload_row_for_report_metadata(session, tmp_path):
    u = User(
        username="alice", nickname="alice",
        hashed_password="x",
    )
    session.add(u)
    await session.flush()
    up = LessonPlanUpload(
        user_id=u.id,
        filename="alice_20260514_plan.pdf",
        original_filename="plan.pdf",
        file_hash="b" * 64,
    )
    session.add(up)
    await session.flush()
    await session.commit()

    svc = LessonPlanAnalysisService(db=session)
    empty_lessonplan_dir = tmp_path / "lessonplan"
    empty_lessonplan_dir.mkdir()
    svc.lessonplan_storage.base_dir = empty_lessonplan_dir

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    with patch.object(
        svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.report_storage, "save_report",
        return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id,
        )

    assert result["success"] is True

    saved = (
        await session.execute(
            select(AnalysisReport).where(AnalysisReport.upload_id == up.id)
        )
    ).scalar_one()
    assert saved.lessonplan_filename == "alice_20260514_plan.pdf"
    assert saved.lessonplan_original_name == "plan.pdf"


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
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
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
            session_id=1, user_id=u.id,
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
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
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
            session_id=1, user_id=u.id,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id
    assert winner_path.exists()


@pytest.mark.asyncio
async def test_analyze_race_loser_does_not_overwrite_winner_file(
    session, tmp_path
):
    u, up = await _seed_user_and_upload(session)

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    winner_path = (
        reports_dir / "alice_20260514010203_plan_reports.md"
    )
    winner_path.write_text("WINNER_CONTENT", encoding="utf-8")

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
    svc.report_storage = ReportStorageService(base_dir=str(reports_dir))

    fake_response = MagicMock()
    fake_response.text = "LOSER_CONTENT"
    fake_response.candidates = []

    real_find = svc._find_existing_report_for_latest_upload
    call_count = {"n": 0}

    async def racing_find(username):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (up, None)
        return await real_find(username)

    class FixedDatetime:
        @classmethod
        def now(cls):
            return datetime(2026, 5, 14, 1, 2, 3)

    with patch.object(
        svc,
        "_find_existing_report_for_latest_upload",
        side_effect=racing_find,
    ), patch.object(
        svc, "_get_store_ids", return_value=["u", "r"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
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
    ), patch(
        "app.services.report_storage_service.datetime",
        FixedDatetime,
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id
    assert winner_path.read_text(encoding="utf-8") == "WINNER_CONTENT"


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
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
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
            session_id=1, user_id=u.id,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id
    assert not orphan_path.exists()


@pytest.mark.asyncio
async def test_analyze_creates_synthetic_upload_for_legacy_user(
    session, tmp_path
):
    """Legacy user has no LessonPlanUpload row. First analysis must create
    a synthetic one so that subsequent clicks are correctly blocked by the
    dedup invariant."""
    u = User(
        username="alice", nickname="alice",
        hashed_password="x",
    )
    session.add(u)
    await session.flush()
    await session.commit()

    lessonplan_dir = tmp_path / "lessonplans"
    user_lp_dir = lessonplan_dir / str(u.id)
    user_lp_dir.mkdir(parents=True)
    lessonplan_path = user_lp_dir / "alice_legacy_plan.pdf"
    lessonplan_path.write_bytes(b"legacy lesson plan")

    report_path = tmp_path / "reports" / "r.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    def save_report(**kwargs):
        report_path.write_text(kwargs["report_content"], encoding="utf-8")
        return {
            "filename": report_path.name,
            "file_path": str(report_path),
        }

    svc = LessonPlanAnalysisService(db=session)
    svc.lessonplan_storage.base_dir = lessonplan_dir

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    with patch.object(
        svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
    ) as mock_stores, patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.report_storage, "save_report", side_effect=save_report,
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id,
        )

    assert result["success"] is True

    # Synthetic upload row was created
    upload = (
        await session.execute(
            select(LessonPlanUpload).where(
                LessonPlanUpload.user_id == u.id
            )
        )
    ).scalar_one()
    assert upload.filename == lessonplan_path.name
    assert upload.original_filename == "alice_legacy_plan.pdf"
    assert upload.file_hash is None

    # Report is linked to the synthetic upload
    saved = (
        await session.execute(
            select(AnalysisReport).where(
                AnalysisReport.upload_id == upload.id
            )
        )
    ).scalar_one()
    assert saved.upload_id == upload.id

    # Second call is blocked by dedup
    second = await svc.analyze_lesson_plan(
        session_id=1, user_id=u.id,
    )
    assert second["success"] is False
    assert second["error_code"] == "ALREADY_ANALYZED"
    assert second["report_id"] == saved.id
    # Gemini was only called once (first call)
    assert mock_stores.call_count == 1


@pytest.mark.asyncio
async def test_legacy_concurrent_analyze_does_not_create_duplicate_reports(
    session, tmp_path
):
    u = User(
        username="alice", nickname="alice",
        hashed_password="x",
    )
    session.add(u)
    await session.flush()
    await session.commit()
    lessonplan_dir = tmp_path / "lessonplans"
    user_lp_dir = lessonplan_dir / str(u.id)
    user_lp_dir.mkdir(parents=True)
    lessonplan_path = user_lp_dir / "alice_legacy_plan.pdf"
    lessonplan_path.write_bytes(b"legacy lesson plan")

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    save_count = {"n": 0}

    def save_report(**kwargs):
        save_count["n"] += 1
        report_path = reports_dir / f"r{save_count['n']}.md"
        report_path.write_text(
            kwargs["report_content"], encoding="utf-8"
        )
        return {
            "filename": report_path.name,
            "file_path": str(report_path),
        }

    svc = LessonPlanAnalysisService(db=session)
    svc.lessonplan_storage.base_dir = lessonplan_dir

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    with patch.object(
        svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.report_storage, "save_report", side_effect=save_report,
    ):
        first = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id,
        )
        await session.commit()

        real_find = svc._find_existing_report_for_latest_upload
        call_count = {"n": 0}

        async def stale_preflight(username):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (None, None)
            return await real_find(username)

        with patch.object(
            svc,
            "_find_existing_report_for_latest_upload",
            side_effect=stale_preflight,
        ):
            second = await svc.analyze_lesson_plan(
                session_id=1, user_id=u.id,
            )
    await session.refresh(u)

    assert first["success"] is True
    assert second["success"] is False
    assert second["error_code"] == "ALREADY_ANALYZED"

    uploads = (
        await session.execute(
            select(LessonPlanUpload).where(
                LessonPlanUpload.user_id == u.id
            )
        )
    ).scalars().all()
    reports = (
        await session.execute(
            select(AnalysisReport).where(AnalysisReport.user_id == u.id)
        )
    ).scalars().all()

    assert len(uploads) == 1
    assert uploads[0].file_hash is None
    assert len(reports) == 1
    assert second["report_id"] == reports[0].id


@pytest.mark.asyncio
async def test_analyze_race_fallback_uses_captured_upload_id_not_latest(
    session,
):
    """When a newer upload appears between pre-flight and the IntegrityError
    fallback, the handler must resolve the winner by the upload_id WE
    attempted (upload_a), not by the latest upload (upload_b)."""
    u = User(
        username="alice", nickname="alice",
        hashed_password="x",
    )
    session.add(u)
    await session.flush()
    upload_a = LessonPlanUpload(
        user_id=u.id,
        filename="alice_plan_a.pdf",
        original_filename="plan_a.pdf",
        file_hash="a" * 64,
    )
    session.add(upload_a)
    await session.flush()
    upload_b = LessonPlanUpload(
        user_id=u.id,
        filename="alice_plan_b.pdf",
        original_filename="plan_b.pdf",
        file_hash="b" * 64,
    )
    session.add(upload_b)
    await session.flush()

    winner = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=upload_a.filename,
        lessonplan_original_name=upload_a.original_filename,
        report_filename="winner.md",
        report_path="/tmp/winner.md",
        upload_id=upload_a.id,
    )
    session.add(winner)
    await session.commit()

    svc = LessonPlanAnalysisService(db=session)

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    call_count = {"n": 0}

    async def racing_find(username):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Pre-flight: latest upload is upload_a, no report
            return (upload_a, None)
        # If the handler re-calls _find_existing... it would see upload_b
        return (upload_b, None)

    with patch.object(
        svc,
        "_find_existing_report_for_latest_upload",
        side_effect=racing_find,
    ), patch.object(
        svc, "_get_store_ids", return_value=["u", "r"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="active"'),
        create=True,
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.report_storage,
        "save_report",
        return_value={"filename": "loser.md", "file_path": "/tmp/loser.md"},
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id
