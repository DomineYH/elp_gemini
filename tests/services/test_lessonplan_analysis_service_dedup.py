"""LessonPlanAnalysisService 중복 분석 차단 동작 테스트."""

import asyncio
import logging
import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from google.genai import errors as genai_errors
from google.genai import types
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
from app.utils.gemini_retry import GeminiQuotaExhausted, GeminiServerOverloaded

# #439: 저장 전 검사를 통과하는 1~5절 제목 본문
VALID_SECTIONS = "".join(f"## {n}. 절\n\n본문\n\n" for n in range(1, 6))


@pytest.fixture(autouse=True)
def gemini_client():
    with patch(
        "app.services.lessonplan_analysis_service.genai.Client",
        return_value=MagicMock(),
    ):
        yield


@pytest_asyncio.fixture
async def session(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        yield s
    await eng.dispose()


async def _seed_user_and_upload(s):
    u = User(
        username="alice",
        nickname="alice",
        hashed_password="x",
    )
    s.add(u)
    await s.flush()
    up = LessonPlanUpload(
        user_id=u.id,
        filename="alice_plan.pdf",
        original_filename="plan.pdf",
        file_hash="a" * 64,
        fs_document_id="documents/a",
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
    with (
        patch.object(svc, "_get_store_ids") as mock_stores,
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search"
        ) as mock_gemini,
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=u.id,
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
    fake_response.text = "# Report\n\nbody\n\n" + VALID_SECTIONS
    fake_response.candidates = []

    with (
        patch.object(
            svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
        ),
        patch.object(svc.prompt_loader, "get_prompt", return_value="SYS"),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="active"'),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search",
            return_value=fake_response,
        ),
        patch.object(
            svc.report_storage,
            "save_report",
            return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
        ),
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=u.id,
        )

    assert result["success"] is True

    saved = (
        await session.execute(
            select(AnalysisReport).where(AnalysisReport.upload_id == up.id)
        )
    ).scalar_one()
    assert saved.upload_id == up.id


NO_DOCUMENT = {
    "success": False,
    "error": "분석할 문서가 없습니다. 수업 지도안을 먼저 업로드해주세요.",
}


@pytest.mark.asyncio
async def test_analyze_returns_upload_required_when_no_upload_or_legacy_file():
    db = MagicMock()
    svc = LessonPlanAnalysisService(db=db)

    with (
        patch.object(
            svc,
            "_find_existing_report_for_latest_upload",
            return_value=(None, None),
        ) as mock_existing,
        patch.object(svc, "_get_store_ids") as mock_stores,
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search"
        ) as mock_gemini,
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=1,
        )

    assert result == NO_DOCUMENT
    mock_existing.assert_called_once_with(1)
    assert mock_stores.call_count == 0
    assert mock_gemini.call_count == 0
    db.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "documents", [["doc1"], []], ids=["문서 있음", "빈 스토어"]
)
async def test_analyze_allows_premigration_file_search_upload_without_row(
    documents,
):
    """업로드 행이 없으면 user-{id}-store 에 문서가 남아 있어도 거부한다 (#468)."""
    db = MagicMock()
    svc = LessonPlanAnalysisService(db=db)

    store = MagicMock()
    store.display_name = "user-1-store"
    store.name = "fileSearchStores/user-store"
    docs = []
    for name in documents:
        doc = MagicMock()
        doc.name = f"fileSearchStores/user-store/documents/{name}"
        doc.display_name = "premigration.pdf"
        docs.append(doc)

    svc.file_search_service.client = MagicMock()
    stores = svc.file_search_service.client.file_search_stores
    stores.list = MagicMock(return_value=[store])
    stores.documents.list = MagicMock(return_value=docs)

    with (
        patch.object(
            svc,
            "_find_existing_report_for_latest_upload",
            return_value=(None, None),
        ),
        patch.object(svc, "_get_store_ids") as mock_stores,
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search"
        ) as mock_gemini,
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=1,
        )

    assert result == NO_DOCUMENT
    stores.list.assert_not_called()
    stores.documents.list.assert_not_called()
    mock_stores.assert_not_called()
    mock_gemini.assert_not_called()
    db.add.assert_not_called()


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
    fake_response.text = "# Report\n\nbody\n\n" + VALID_SECTIONS
    fake_response.candidates = []

    saved_report_path = tmp_path / "saved_report.md"

    def save_report(**kwargs):
        saved_report_path.write_text(kwargs["report_content"], encoding="utf-8")
        return {
            "filename": saved_report_path.name,
            "file_path": str(saved_report_path),
        }

    with (
        patch.object(
            svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
        ),
        patch.object(svc.prompt_loader, "get_prompt", return_value="SYS"),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="active"'),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search",
            return_value=fake_response,
        ) as mock_gemini,
        patch.object(
            svc.report_storage,
            "save_report",
            side_effect=save_report,
        ),
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=u.id,
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
        username="alice",
        nickname="alice",
        hashed_password="x",
    )
    session.add(u)
    await session.flush()
    up = LessonPlanUpload(
        user_id=u.id,
        filename="alice_20260514_plan.pdf",
        original_filename="plan.pdf",
        file_hash="b" * 64,
        fs_document_id="documents/a",
    )
    session.add(up)
    await session.flush()
    await session.commit()

    svc = LessonPlanAnalysisService(db=session)

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody\n\n" + VALID_SECTIONS
    fake_response.candidates = []

    with (
        patch.object(
            svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
        ),
        patch.object(svc.prompt_loader, "get_prompt", return_value="SYS"),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="active"'),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search",
            return_value=fake_response,
        ),
        patch.object(
            svc.report_storage,
            "save_report",
            return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
        ),
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=u.id,
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
    fake_response.text = "# Report\n\nbody\n\n" + VALID_SECTIONS
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

    with (
        patch.object(
            svc,
            "_find_existing_report_for_latest_upload",
            side_effect=racing_find,
        ),
        patch.object(svc, "_get_store_ids", return_value=["u", "r"]),
        patch.object(svc.prompt_loader, "get_prompt", return_value="SYS"),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="active"'),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search",
            return_value=fake_response,
        ),
        patch.object(
            svc.report_storage,
            "save_report",
            return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
        ),
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=u.id,
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
    fake_response.text = "# Report\n\nbody\n\n" + VALID_SECTIONS
    fake_response.candidates = []

    real_find = svc._find_existing_report_for_latest_upload
    call_count = {"n": 0}

    async def racing_find(username):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (up, None)
        return await real_find(username)

    with (
        patch.object(
            svc,
            "_find_existing_report_for_latest_upload",
            side_effect=racing_find,
        ),
        patch.object(svc, "_get_store_ids", return_value=["u", "r"]),
        patch.object(svc.prompt_loader, "get_prompt", return_value="SYS"),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="active"'),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search",
            return_value=fake_response,
        ),
        patch.object(
            svc.report_storage,
            "save_report",
            return_value={
                "filename": winner_path.name,
                "file_path": str(winner_path),
            },
        ),
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=u.id,
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
    winner_path = reports_dir / "alice_20260514010203_plan_reports.md"
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
    fake_response.text = "LOSER_CONTENT\n\n" + VALID_SECTIONS
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

    with (
        patch.object(
            svc,
            "_find_existing_report_for_latest_upload",
            side_effect=racing_find,
        ),
        patch.object(svc, "_get_store_ids", return_value=["u", "r"]),
        patch.object(svc.prompt_loader, "get_prompt", return_value="SYS"),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="active"'),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search",
            return_value=fake_response,
        ),
        patch(
            "app.services.report_storage_service.datetime",
            FixedDatetime,
        ),
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=u.id,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id
    assert winner_path.read_text(encoding="utf-8") == "WINNER_CONTENT"


@pytest.mark.asyncio
async def test_analyze_race_fallback_cleans_up_orphan_report(session, tmp_path):
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
    fake_response.text = "# Report\n\nbody\n\n" + VALID_SECTIONS
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

    with (
        patch.object(
            svc,
            "_find_existing_report_for_latest_upload",
            side_effect=racing_find,
        ),
        patch.object(svc, "_get_store_ids", return_value=["u", "r"]),
        patch.object(svc.prompt_loader, "get_prompt", return_value="SYS"),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="active"'),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search",
            return_value=fake_response,
        ),
        patch.object(
            svc.report_storage,
            "save_report",
            side_effect=save_orphan_report,
        ),
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=u.id,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id
    assert not orphan_path.exists()


def _legacy_lessonplan_file(tmp_path, monkeypatch, user_id):
    """옛 경로 data/lessonplan/{id}/ 에 업로드 행 없는 지도안 파일을 둔다."""
    monkeypatch.chdir(tmp_path)
    user_lp_dir = tmp_path / "data" / "lessonplan" / str(user_id)
    user_lp_dir.mkdir(parents=True)
    (user_lp_dir / "alice_legacy_plan.pdf").write_bytes(b"legacy lesson plan")
    return tmp_path / "reports"


@pytest.mark.asyncio
async def test_analyze_creates_synthetic_upload_for_legacy_user(
    session, tmp_path, monkeypatch
):
    """업로드 행 없이 옛 폴더에만 파일이 있으면 합성 행을 만들지 않고 거부한다 (#468)."""
    u = User(
        username="alice",
        nickname="alice",
        hashed_password="x",
    )
    session.add(u)
    await session.flush()
    await session.commit()
    user_id = u.id
    reports_dir = _legacy_lessonplan_file(tmp_path, monkeypatch, user_id)

    svc = LessonPlanAnalysisService(db=session)
    svc.report_storage = ReportStorageService(base_dir=str(reports_dir))

    with (
        patch.object(svc, "_get_store_ids") as mock_stores,
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search"
        ) as mock_gemini,
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=user_id,
        )

    assert result == NO_DOCUMENT
    mock_stores.assert_not_called()
    mock_gemini.assert_not_called()
    assert (
        await session.execute(
            select(LessonPlanUpload).where(LessonPlanUpload.user_id == user_id)
        )
    ).scalars().all() == []
    assert list(reports_dir.rglob("*.md")) == []


@pytest.mark.asyncio
async def test_legacy_concurrent_analyze_does_not_create_duplicate_reports(
    session, tmp_path, monkeypatch
):
    u = User(
        username="alice",
        nickname="alice",
        hashed_password="x",
    )
    session.add(u)
    await session.flush()
    await session.commit()
    user_id = u.id
    reports_dir = _legacy_lessonplan_file(tmp_path, monkeypatch, user_id)

    svc = LessonPlanAnalysisService(db=session)
    svc.report_storage = ReportStorageService(base_dir=str(reports_dir))

    with (
        patch.object(svc, "_get_store_ids") as mock_stores,
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search"
        ) as mock_gemini,
    ):
        first, second = await asyncio.gather(
            svc.analyze_lesson_plan(session_id=1, user_id=user_id),
            svc.analyze_lesson_plan(session_id=1, user_id=user_id),
        )

    assert first == second == NO_DOCUMENT
    mock_stores.assert_not_called()
    mock_gemini.assert_not_called()
    for model in (LessonPlanUpload, AnalysisReport):
        rows = (
            await session.execute(select(model).where(model.user_id == user_id))
        ).scalars()
        assert rows.all() == []
    assert list(reports_dir.rglob("*.md")) == []


@pytest.mark.asyncio
async def test_analyze_race_fallback_uses_captured_upload_id_not_latest(
    session,
):
    """When a newer upload appears between pre-flight and the IntegrityError
    fallback, the handler must resolve the winner by the upload_id WE
    attempted (upload_a), not by the latest upload (upload_b)."""
    u = User(
        username="alice",
        nickname="alice",
        hashed_password="x",
    )
    session.add(u)
    await session.flush()
    upload_a = LessonPlanUpload(
        user_id=u.id,
        filename="alice_plan_a.pdf",
        original_filename="plan_a.pdf",
        file_hash="a" * 64,
        fs_document_id="documents/a",
    )
    session.add(upload_a)
    await session.flush()
    upload_b = LessonPlanUpload(
        user_id=u.id,
        filename="alice_plan_b.pdf",
        original_filename="plan_b.pdf",
        file_hash="b" * 64,
        fs_document_id="documents/b",
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
    fake_response.text = "# Report\n\nbody\n\n" + VALID_SECTIONS
    fake_response.candidates = []

    call_count = {"n": 0}

    async def racing_find(username):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Pre-flight: latest upload is upload_a, no report
            return (upload_a, None)
        # If the handler re-calls _find_existing... it would see upload_b
        return (upload_b, None)

    with (
        patch.object(
            svc,
            "_find_existing_report_for_latest_upload",
            side_effect=racing_find,
        ),
        patch.object(svc, "_get_store_ids", return_value=["u", "r"]),
        patch.object(svc.prompt_loader, "get_prompt", return_value="SYS"),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="active"'),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search",
            return_value=fake_response,
        ),
        patch.object(
            svc.report_storage,
            "save_report",
            return_value={"filename": "loser.md", "file_path": "/tmp/loser.md"},
        ),
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1,
            user_id=u.id,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id


# ===== #439 저장 전 검사 + 1회 재시도 =====

SERVICE_LOGGER = "app.services.lessonplan_analysis_service"
INVALID_REPORT = {
    "success": False,
    "error_code": "INVALID_REPORT",
    "error": "분석 결과가 올바르게 만들어지지 않았습니다. 다시 시도해주세요.",
}


def _response(text, finish_reason=None, tokens=6366):
    """2패스 응답 대역. finish_reason 이 None 이면 후보 없음(미상)."""
    return SimpleNamespace(
        text=text,
        candidates=(
            []
            if finish_reason is None
            else [
                SimpleNamespace(
                    finish_reason=finish_reason, grounding_metadata=None
                )
            ]
        ),
        usage_metadata=SimpleNamespace(candidates_token_count=tokens),
    )


def _analysis_patches(svc, gemini_results):
    return (
        patch.object(
            svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
        ),
        patch.object(svc.prompt_loader, "get_prompt", return_value="SYS"),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="active"'),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service."
            "_call_gemini_with_file_search",
            side_effect=gemini_results,
        ),
    )


async def _analyze(svc, user_id, gemini_results):
    """Gemini 래퍼가 gemini_results 를 차례로 돌려주게 하고 분석한다."""
    stores, prompt, criteria, gemini = _analysis_patches(svc, gemini_results)
    with (
        stores,
        prompt,
        criteria,
        gemini as mock_gemini,
        patch.object(
            svc.report_storage,
            "save_report",
            return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
        ) as mock_save,
    ):
        result = await svc.analyze_lesson_plan(session_id=1, user_id=user_id)
    return result, mock_gemini, mock_save


async def _report_rows(session, upload_id):
    rows = await session.execute(
        select(AnalysisReport).where(AnalysisReport.upload_id == upload_id)
    )
    return rows.scalars().all()


def _messages(caplog, level, needle):
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == level and needle in r.getMessage()
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first",
    [
        None,
        _response("# Report\n\n## 1. 절\n\nBADMARK"),
        _response(
            "BADMARK\n\n" + VALID_SECTIONS, types.FinishReason.MAX_TOKENS
        ),
    ],
    ids=["정상 1회", "2-5절 없음 → 재시도", "MAX_TOKENS → 재시도"],
)
async def test_analyze_saves_first_report_that_passes_check(
    session, caplog, first
):
    u, up = await _seed_user_and_upload(session)
    svc = LessonPlanAnalysisService(db=session)
    good_text = "GOODMARK\n\n" + VALID_SECTIONS
    good = _response(good_text, types.FinishReason.STOP, tokens=7090)
    responses = [good] if first is None else [first, good]

    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        result, mock_gemini, mock_save = await _analyze(svc, u.id, responses)

    assert result["success"] is True
    assert mock_gemini.call_count == len(responses)
    mock_save.assert_called_once()
    saved = mock_save.call_args.kwargs["report_content"]
    assert "GOODMARK" in saved
    assert "BADMARK" not in saved
    assert len(await _report_rows(session, up.id)) == 1

    warnings = _messages(caplog, logging.WARNING, "검사 실패")
    assert len(warnings) == len(responses) - 1
    infos = _messages(caplog, logging.INFO, "분석 응답")
    assert len(infos) == len(responses)
    assert "finish_reason=STOP" in infos[-1]
    assert "output_tokens=7090" in infos[-1]
    assert f"chars={len(good_text)}" in infos[-1]
    assert "BADMARK" not in caplog.text
    assert "GOODMARK" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_text",
    [VALID_SECTIONS + "도입 단계에서" + "거" * 30, ""],
    ids=["같은 글자 30회", "빈 응답"],
)
async def test_analyze_returns_invalid_report_and_saves_nothing(
    session, caplog, bad_text
):
    u, up = await _seed_user_and_upload(session)
    svc = LessonPlanAnalysisService(db=session)

    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        result, mock_gemini, mock_save = await _analyze(
            svc, u.id, [_response(bad_text), _response(bad_text)]
        )

    assert result == INVALID_REPORT
    assert mock_gemini.call_count == 2
    mock_save.assert_not_called()
    assert await _report_rows(session, up.id) == []
    assert len(_messages(caplog, logging.INFO, "분석 응답")) == 2
    assert len(_messages(caplog, logging.WARNING, "검사 실패")) == 2
    assert "거거거" not in caplog.text

    # 실패 직후 같은 업로드: 409 가 아니라 새로 분석된다
    retry, mock_gemini, mock_save = await _analyze(
        svc, u.id, [_response(VALID_SECTIONS)]
    )
    assert retry["success"] is True
    assert mock_gemini.call_count == 1
    mock_save.assert_called_once()
    assert len(await _report_rows(session, up.id)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, code",
    [
        (GeminiQuotaExhausted("429"), "RESOURCE_EXHAUSTED"),
        (GeminiServerOverloaded("503"), "MODEL_OVERLOADED"),
    ],
    ids=["429", "503"],
)
async def test_analyze_does_not_retry_check_on_api_error(session, error, code):
    u, up = await _seed_user_and_upload(session)
    svc = LessonPlanAnalysisService(db=session)

    result, mock_gemini, mock_save = await _analyze(svc, u.id, [error])

    assert result["success"] is False
    assert result["error_code"] == code
    assert mock_gemini.call_count == 1
    mock_save.assert_not_called()
    assert await _report_rows(session, up.id) == []


@pytest.mark.asyncio
async def test_analyze_retry_then_race_falls_back_to_already_analyzed(
    session, tmp_path
):
    u, up = await _seed_user_and_upload(session)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    winner_path = reports_dir / "winner.md"
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
    winner_id, upload_id = winner.id, up.id

    svc = LessonPlanAnalysisService(db=session)
    svc.report_storage = ReportStorageService(base_dir=str(reports_dir))
    real_find = svc._find_existing_report_for_latest_upload
    calls = {"n": 0}

    async def racing_find(user_id):
        # 사전 확인 때는 아직 승자 보고서가 없었던 것처럼 보인다
        calls["n"] += 1
        if calls["n"] == 1:
            return (up, None)
        return await real_find(user_id)

    stores, prompt, criteria, gemini = _analysis_patches(
        svc, [_response("## 1. 절\n"), _response(VALID_SECTIONS)]
    )
    with (
        patch.object(
            svc,
            "_find_existing_report_for_latest_upload",
            side_effect=racing_find,
        ),
        stores,
        prompt,
        criteria,
        gemini as mock_gemini,
    ):
        result = await svc.analyze_lesson_plan(session_id=1, user_id=u.id)

    assert mock_gemini.call_count == 2
    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner_id
    files = [p.name for p in reports_dir.rglob("*") if p.is_file()]
    assert files == ["winner.md"]
    assert winner_path.read_text(encoding="utf-8") == "WINNER_CONTENT"
    assert [r.id for r in await _report_rows(session, upload_id)] == [winner_id]


@pytest.mark.asyncio
async def test_analyze_timeout_covers_check_retry(session):
    u, up = await _seed_user_and_upload(session)
    svc = LessonPlanAnalysisService(db=session)
    release = threading.Event()
    calls = []

    def gemini(*args):
        calls.append(args)
        if len(calls) == 1:
            return _response("## 1. 절\n")
        release.wait(5)  # 마감이 지날 때까지 둘째 시도를 붙잡는다
        return _response(VALID_SECTIONS)

    real_timeout = asyncio.timeout
    deadlines = []

    def short_timeout(seconds):
        deadlines.append(seconds)
        return real_timeout(1.0)

    stores, prompt, criteria, _ = _analysis_patches(svc, None)
    try:
        with (
            stores,
            prompt,
            criteria,
            patch(
                "app.services.lessonplan_analysis_service."
                "_call_gemini_with_file_search",
                side_effect=gemini,
            ),
            patch(
                "app.services.lessonplan_analysis_service.asyncio.timeout",
                side_effect=short_timeout,
            ),
            patch.object(svc.report_storage, "save_report") as mock_save,
        ):
            result = await svc.analyze_lesson_plan(session_id=1, user_id=u.id)
    finally:
        release.set()

    assert result == {"success": False, "error": "분석 시간 초과 (180초)"}
    assert deadlines == [180]
    assert len(calls) == 2
    mock_save.assert_not_called()
    assert await _report_rows(session, up.id) == []


# ===== #449 1패스 지도안 검색 실패도 같은 시도 예산을 쓴다 =====

NOT_RETRIEVED = {
    "success": False,
    "error_code": "LESSONPLAN_NOT_RETRIEVED",
    "error": (
        "업로드한 지도안 내용을 읽지 못했습니다. "
        "지도안을 다시 업로드한 뒤 분석해 주세요."
    ),
}
NOTICE = "업로드된 수업 지도안 문서가 확인되지 않습니다. NOTICEMARK"


def _pass1(text, chunks):
    return SimpleNamespace(
        text=text,
        candidates=[
            SimpleNamespace(
                grounding_metadata=SimpleNamespace(
                    grounding_chunks=[object()] * chunks
                )
            )
        ],
    )


def _fake_models(steps):
    """steps: 1패스/2패스 응답(또는 예외)을 차례로 돌려주는 대역.

    도구의 스토어 이름으로 어느 패스의 호출인지 기록한다.
    """
    seen = []
    queue = list(steps)

    def generate_content(model, contents, config):
        (store,) = config.tools[0].file_search.file_search_store_names
        seen.append("pass1" if store == "user-store" else "pass2")
        step = queue.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    return generate_content, seen


async def _analyze_real_wrapper(svc, user_id, steps):
    generate_content, seen = _fake_models(steps)
    svc.client.models.generate_content = MagicMock(side_effect=generate_content)
    stores, prompt, criteria, _ = _analysis_patches(svc, None)
    with (
        stores,
        prompt,
        criteria,
        patch.object(
            svc.report_storage,
            "save_report",
            return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
        ) as mock_save,
    ):
        result = await svc.analyze_lesson_plan(session_id=1, user_id=user_id)
    return result, seen, mock_save


GROUNDED = _pass1("지도안 원문", 2)
UNGROUNDED = _pass1(NOTICE, 0)
GOOD = _response(VALID_SECTIONS, types.FinishReason.STOP)
BAD = _response("## 1. 절\n", types.FinishReason.STOP)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "steps, seen, expected, warnings",
    [
        ([GROUNDED, GOOD], ["pass1", "pass2"], None, 0),
        (
            [UNGROUNDED, GROUNDED, GOOD],
            ["pass1", "pass1", "pass2"],
            None,
            1,
        ),
        ([UNGROUNDED, UNGROUNDED], ["pass1", "pass1"], NOT_RETRIEVED, 2),
        (
            [UNGROUNDED, GROUNDED, BAD],
            ["pass1", "pass1", "pass2"],
            INVALID_REPORT,
            2,
        ),
        (
            [GROUNDED, BAD, UNGROUNDED],
            ["pass1", "pass2", "pass1"],
            NOT_RETRIEVED,
            2,
        ),
    ],
    ids=[
        "정상 1+1",
        "안내문 → 정상",
        "두 번 다 근거 없음",
        "검색 실패 → 보고서 실패",
        "보고서 실패 → 검색 실패",
    ],
)
async def test_retrieval_retry_shares_report_budget(
    session, caplog, steps, seen, expected, warnings
):
    u, up = await _seed_user_and_upload(session)
    svc = LessonPlanAnalysisService(db=session)

    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        result, actual_seen, mock_save = await _analyze_real_wrapper(
            svc, u.id, steps
        )

    assert actual_seen == seen
    if expected is None:
        assert result["success"] is True
        mock_save.assert_called_once()
        assert len(await _report_rows(session, up.id)) == 1
    else:
        assert result == expected
        mock_save.assert_not_called()
        assert await _report_rows(session, up.id) == []
    assert len(_messages(caplog, logging.WARNING, "검사 실패")) == warnings
    pass1_logs = _messages(caplog, logging.INFO, "분석 1패스")
    expected_logs = [
        (
            "chars=6 grounding_chunks=2"
            if step is GROUNDED
            else f"chars={len(NOTICE)} grounding_chunks=0"
        )
        for step in steps
        if step is GROUNDED or step is UNGROUNDED
    ]
    assert len(pass1_logs) == len(expected_logs)
    for log, expected_log in zip(pass1_logs, expected_logs):
        assert expected_log in log
    assert "NOTICEMARK" not in caplog.text


@pytest.mark.asyncio
async def test_retrieval_failure_leaves_upload_retryable(session):
    u, up = await _seed_user_and_upload(session)
    svc = LessonPlanAnalysisService(db=session)

    result, seen, mock_save = await _analyze_real_wrapper(
        svc, u.id, [UNGROUNDED, UNGROUNDED]
    )
    assert result == NOT_RETRIEVED
    mock_save.assert_not_called()

    # 실패 직후 같은 업로드: 409 가 아니라 새로 분석된다
    retry, seen, mock_save = await _analyze_real_wrapper(
        svc, u.id, [GROUNDED, GOOD]
    )
    assert retry["success"] is True
    assert seen == ["pass1", "pass2"]
    mock_save.assert_called_once()
    assert len(await _report_rows(session, up.id)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, code",
    [
        (
            genai_errors.ClientError(
                429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}
            ),
            "RESOURCE_EXHAUSTED",
        ),
        (
            genai_errors.ServerError(
                503, {"error": {"code": 503, "status": "UNAVAILABLE"}}
            ),
            "MODEL_OVERLOADED",
        ),
    ],
    ids=["429", "503"],
)
async def test_pass1_api_error_keeps_status(session, error, code):
    u, up = await _seed_user_and_upload(session)
    svc = LessonPlanAnalysisService(db=session)

    # SDK 일시 장애 재시도(기존 3회)는 대기 없이 돌린다
    with patch("tenacity.nap.time.sleep"):
        result, seen, mock_save = await _analyze_real_wrapper(
            svc, u.id, [error, error, error, GROUNDED, GOOD]
        )

    assert result["success"] is False
    assert result["error_code"] == code
    assert seen == ["pass1", "pass1", "pass1"]
    mock_save.assert_not_called()
    assert await _report_rows(session, up.id) == []


# ===== #450 최신 업로드의 검색 색인 사전 확인 =====

INDEX_MISSING = {
    "success": False,
    "error_code": "LESSONPLAN_INDEX_MISSING",
    "error": "지도안 검색 색인이 없습니다. 지도안을 다시 업로드한 뒤 분석해 주세요.",
}


async def _analyze_tracked(svc, user_id, gemini_results):
    """_analyze 와 같되 스토어 조회 대역도 돌려준다."""
    stores, prompt, criteria, gemini = _analysis_patches(svc, gemini_results)
    with (
        stores as mock_stores,
        prompt,
        criteria,
        gemini as mock_gemini,
        patch.object(
            svc.report_storage,
            "save_report",
            return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
        ) as mock_save,
    ):
        result = await svc.analyze_lesson_plan(session_id=1, user_id=user_id)
    return result, mock_stores, mock_gemini, mock_save


def _assert_stopped_before_model(svc, mock_stores, mock_gemini, mock_save):
    mock_stores.assert_not_called()
    mock_gemini.assert_not_called()
    svc.client.models.generate_content.assert_not_called()
    mock_save.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("document_id", [None, ""], ids=["None", "빈 문자열"])
async def test_missing_index_stops_before_store_lookup(session, document_id):
    u, up = await _seed_user_and_upload(session)
    up.fs_document_id = document_id
    await session.commit()
    svc = LessonPlanAnalysisService(db=session)

    result, mock_stores, mock_gemini, mock_save = await _analyze_tracked(
        svc, u.id, [_response(VALID_SECTIONS)]
    )

    assert result == INDEX_MISSING
    _assert_stopped_before_model(svc, mock_stores, mock_gemini, mock_save)
    assert await _report_rows(session, up.id) == []


@pytest.mark.asyncio
async def test_existing_report_precedes_missing_index(session, tmp_path):
    u, up = await _seed_user_and_upload(session)
    up.fs_document_id = None
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

    result, mock_stores, mock_gemini, mock_save = await _analyze_tracked(
        svc, u.id, [_response(VALID_SECTIONS)]
    )

    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == existing.id
    _assert_stopped_before_model(svc, mock_stores, mock_gemini, mock_save)


@pytest.mark.asyncio
async def test_missing_file_then_missing_index(session, tmp_path):
    u, up = await _seed_user_and_upload(session)
    up.fs_document_id = None
    stale = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=up.filename,
        lessonplan_original_name=up.original_filename,
        report_filename="gone.md",
        report_path=str(tmp_path / "gone.md"),
        upload_id=up.id,
    )
    session.add(stale)
    await session.commit()
    upload_id = up.id
    svc = LessonPlanAnalysisService(db=session)

    result, mock_stores, mock_gemini, mock_save = await _analyze_tracked(
        svc, u.id, [_response(VALID_SECTIONS)]
    )

    assert result == INDEX_MISSING
    _assert_stopped_before_model(svc, mock_stores, mock_gemini, mock_save)
    # 파일 없는 보고서 행은 기존대로 정리된다
    assert await _report_rows(session, upload_id) == []


@pytest.mark.asyncio
async def test_analyze_during_and_after_reindex(session):
    from app.services.simulation.lessonplan_source import (
        forget_file_search_ids,
    )

    u, upload_a = await _seed_user_and_upload(session)
    user_id, upload_a_id = u.id, upload_a.id
    svc = LessonPlanAnalysisService(db=session)

    # B 업로드가 스토어를 지우고 색인 id 를 비운 직후(B 행은 아직 없음)
    await forget_file_search_ids(session, user_id)
    result, mock_stores, mock_gemini, mock_save = await _analyze_tracked(
        svc, user_id, [_response("BMARK\n\n" + VALID_SECTIONS)]
    )
    assert result == INDEX_MISSING
    _assert_stopped_before_model(svc, mock_stores, mock_gemini, mock_save)

    # B 의 외부 색인은 끝났지만 B 행 commit 전: 스토어에는 B 문서가 있다
    from tests.unit.test_qna_store_user_id_keying import FakeGenai

    fake = FakeGenai(user_id)
    with patch.object(svc.file_search_service, "client", fake):
        result, mock_stores, mock_gemini, mock_save = await _analyze_tracked(
            svc, user_id, [_response("BMARK\n\n" + VALID_SECTIONS)]
        )
    assert result == INDEX_MISSING
    _assert_stopped_before_model(svc, mock_stores, mock_gemini, mock_save)
    assert fake.calls == {}
    assert await _report_rows(session, upload_a_id) == []

    # B 행 commit 뒤: B 로 분석되고 B 행에 저장된다
    upload_b = LessonPlanUpload(
        user_id=user_id,
        filename="alice_plan_b.pdf",
        original_filename="plan_b.pdf",
        file_hash="b" * 64,
        fs_document_id="documents/b",
    )
    session.add(upload_b)
    await session.commit()
    upload_b_id = upload_b.id

    result, mock_stores, mock_gemini, mock_save = await _analyze_tracked(
        svc, user_id, [_response("BMARK\n\n" + VALID_SECTIONS)]
    )
    assert result["success"] is True
    assert mock_save.call_args.kwargs["original_filename"] == "plan_b.pdf"
    assert "BMARK" in mock_save.call_args.kwargs["report_content"]
    assert await _report_rows(session, upload_a_id) == []
    (row,) = await _report_rows(session, upload_b_id)
    assert row.lessonplan_filename == "alice_plan_b.pdf"
    assert row.lessonplan_original_name == "plan_b.pdf"


# --- #468 B: 업로드 행이 없으면 남은 스토어가 있어도 분석하지 않는다 ---------


@pytest_asyncio.fixture
async def analyze_post(session, tmp_path, monkeypatch):
    """가짜 SDK 로 실제 분석 라우트·서비스를 부른다. (응답, fake)."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.db import get_db
    from app.dependencies import get_current_user
    from app.routers import lessonplan_analysis
    from app.services.file_search_service import FileSearchService
    from tests.unit.test_qna_store_user_id_keying import FakeGenai

    # 보고서·옛 지도안 폴더(상대 경로)를 tmp 안에 둔다
    monkeypatch.chdir(tmp_path)
    user = User(username="newcomer", nickname="newcomer", hashed_password="x")
    session.add(user)
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    test_app = FastAPI()
    test_app.include_router(lessonplan_analysis.router)

    async def override_get_db():
        async with factory() as db:
            yield db

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_user] = lambda: user

    async def _post():
        fake = FakeGenai(user.id, answer=VALID_SECTIONS)
        monkeypatch.setattr(FileSearchService, "_client", fake)
        with (
            patch(
                "app.services.lessonplan_analysis_service.genai.Client",
                return_value=fake,
            ),
            patch(
                "app.services.prompt_loader_service.PromptLoaderService.get_prompt",
                return_value="SYS",
            ),
            patch(
                "app.services.criteria_vector_service."
                "CriteriaVectorService.active_stable_id_filter",
                new=AsyncMock(return_value='stable_id="A"'),
            ),
            patch.object(
                LessonPlanAnalysisService,
                "_collect_active_criteria_display_names",
                new=AsyncMock(return_value=[]),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/api/lessonplan/analyze", json={"session_id": 1}
                )
        return response, fake

    return user, _post


async def _user_rows(session, model, user_id):
    # 요청이 쓴 별도 세션의 결과를 새 세션으로 읽는다
    async with async_sessionmaker(session.bind)() as db:
        return (
            (await db.execute(select(model).where(model.user_id == user_id)))
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_analyze_rejects_orphan_store_without_upload(
    session, analyze_post
):
    user, post = analyze_post

    response, fake = await post()

    assert response.status_code == 500, response.text
    assert response.json() == {
        "detail": "분석할 문서가 없습니다. 수업 지도안을 먼저 업로드해주세요."
    }
    assert fake.calls == {}
    assert await _user_rows(session, AnalysisReport, user.id) == []
    assert await _user_rows(session, LessonPlanUpload, user.id) == []


@pytest.mark.asyncio
async def test_indexed_upload_keeps_analysis_search(session, analyze_post):
    user, post = analyze_post
    upload = LessonPlanUpload(
        user_id=user.id,
        filename="newcomer_plan.pdf",
        original_filename="plan.pdf",
        fs_document_id="documents/new",
    )
    session.add(upload)
    await session.commit()

    response, fake = await post()

    assert response.status_code == 200, response.text
    assert fake.calls["stores.create"] == 0
    pass1, final = fake.configs
    assert [t.file_search.file_search_store_names for t in pass1.tools] == [
        [fake.user_store]
    ]
    assert [
        (t.file_search.file_search_store_names, t.file_search.metadata_filter)
        for t in final.tools
    ] == [(["fileSearchStores/rubric"], 'stable_id="A"')]
    (row,) = await _user_rows(session, AnalysisReport, user.id)
    assert (row.upload_id, row.lessonplan_original_name) == (
        upload.id,
        "plan.pdf",
    )
