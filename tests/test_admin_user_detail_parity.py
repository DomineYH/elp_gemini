"""
Parity invariant: a user's dashboard endpoints and the admin per-user endpoints
must return the same set of sessions and reports when looking at the same user.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, get_db
from app.dependencies import get_current_admin, get_current_user
from app.main import app
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.users import User
from tests.conftest import (
    TestingSessionLocal,
    engine,
    override_admin,
    override_get_db,
)

_admin = User(
    id=999,
    username="parity_admin",
    nickname="ParityAdmin",
    hashed_password="hashed",
    is_admin=True,
)


def _override_current_user(user: User):
    async def _factory():
        return user

    return _factory


@pytest_asyncio.fixture
async def parity_setup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as db:
        owner = User(
            username="parity_user",
            nickname="Parity",
            hashed_password="h",
            is_admin=False,
        )
        db.add(owner)
        await db.flush()

        base_time = datetime(2026, 5, 11, 9, 0, 0)
        s1 = ChatSession(
            user_id=owner.id,
            user_type="1학년",
            title="대화1",
            created_at=base_time,
            updated_at=base_time + timedelta(minutes=10),
        )
        s2 = ChatSession(
            user_id=owner.id,
            user_type="2학년",
            title="대화2",
            created_at=base_time + timedelta(hours=1),
            updated_at=base_time + timedelta(hours=1, minutes=5),
        )
        db.add_all([s1, s2])
        await db.flush()
        db.add(
            ChatMessage(
                session_id=s1.id,
                role=MessageRole.USER,
                content="최근 메시지",
                created_at=base_time + timedelta(hours=2),
            )
        )

        r1 = AnalysisReport(
            user_id=owner.id,
            lessonplan_filename="lp1.pdf",
            lessonplan_original_name="지도안1.pdf",
            report_filename="report1.md",
            report_path="/tmp/report1.md",
            latency_ms=1000,
            created_at=base_time,
        )
        r2 = AnalysisReport(
            user_id=owner.id,
            lessonplan_filename="lp2.pdf",
            lessonplan_original_name="지도안2.pdf",
            report_filename="report2.md",
            report_path="/tmp/report2.md",
            latency_ms=1200,
            created_at=base_time + timedelta(hours=1),
        )
        db.add_all([r1, r2])
        await db.commit()
        owner_id = owner.id

    yield {"owner_id": owner_id}

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_user_dashboard_and_admin_view_return_same_sessions(parity_setup):
    owner_id = parity_setup["owner_id"]

    async with TestingSessionLocal() as db:
        owner = await db.get(User, owner_id)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_admin(_admin)
    app.dependency_overrides[get_current_user] = _override_current_user(owner)
    try:
        with TestClient(app) as client:
            user_resp = client.get("/api/qna/sessions?limit=50&offset=0")
            admin_resp = client.get(
                f"/admin/api/users/{owner_id}/sessions?limit=50&offset=0"
            )
        assert user_resp.status_code == 200
        assert admin_resp.status_code == 200
        user_ids = [s["session_id"] for s in user_resp.json()["sessions"]]
        admin_ids = [s["session_id"] for s in admin_resp.json()["sessions"]]
        assert user_ids == admin_ids
        assert (
            user_resp.json()["total_count"] == admin_resp.json()["total_count"]
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_user_dashboard_and_admin_view_return_same_reports(parity_setup):
    owner_id = parity_setup["owner_id"]

    async with TestingSessionLocal() as db:
        owner = await db.get(User, owner_id)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_admin(_admin)
    app.dependency_overrides[get_current_user] = _override_current_user(owner)
    try:
        with TestClient(app) as client:
            user_resp = client.get("/api/lessonplan/reports")
            admin_resp = client.get(
                f"/admin/api/users/{owner_id}/reports?limit=100&offset=0"
            )
        assert user_resp.status_code == 200
        assert admin_resp.status_code == 200
        user_ids = [r["id"] for r in user_resp.json()["reports"]]
        admin_ids = [r["id"] for r in admin_resp.json()["reports"]]
        assert user_ids == admin_ids
    finally:
        app.dependency_overrides.clear()


def _js_function_body(source, start, end):
    return source[source.index(start) : source.index(end)]


def test_render_resets_bulk_bar_after_list_rerender():
    """#183: 삭제 후 재렌더링되면 선택 바도 새 체크박스 상태로 맞춘다."""
    from pathlib import Path

    source = Path("app/templates/admin/admin_user_detail.html").read_text(
        encoding="utf-8"
    )
    for render, next_fn, update in [
        (
            "function renderSessions",
            "async function loadSessions",
            "updateBulkSessionBar();",
        ),
        (
            "function renderReports",
            "async function loadReports",
            "updateBulkReportBar();",
        ),
    ]:
        body = _js_function_body(source, render, next_fn)
        empty_branch, _, filled_branch = body.partition("return;")
        # 전부 삭제된 경우(빈 목록 분기)와 남은 항목이 있는 경우 모두
        assert update in empty_branch, render
        assert update in filled_branch, render


_REPORT_ITEM_KEYS = {
    "id",
    "lessonplan_filename",
    "lessonplan_original_name",
    "report_filename",
    "latency_ms",
    "created_at",
}


@pytest.mark.asyncio
async def test_report_list_hides_server_path(parity_setup):
    """#451: 보고서 목록은 서버 파일 경로를 내려 주지 않는다."""
    owner_id = parity_setup["owner_id"]
    async with TestingSessionLocal() as db:
        owner = await db.get(User, owner_id)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user(owner)
    try:
        with TestClient(app) as client:
            resp = client.get("/api/lessonplan/reports")
        assert resp.status_code == 200
        reports = resp.json()["reports"]
        assert len(reports) == 2
        for item in reports:
            assert set(item) == _REPORT_ITEM_KEYS
        assert "/tmp/report1.md" not in resp.text
        assert "/tmp/report2.md" not in resp.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_analyze_returns_public_saved_report(parity_setup, monkeypatch):
    """#451: 분석 응답의 saved_report에는 파일명과 시각만 있다."""
    from app.routers import lessonplan_analysis

    owner_id = parity_setup["owner_id"]
    async with TestingSessionLocal() as db:
        owner = await db.get(User, owner_id)

    async def fake_analyze(self, session_id, user_id):
        return {
            "success": True,
            "report": "# 보고서",
            "latency_ms": 10,
            "saved_report": {
                "filename": "new_report.md",
                "file_path": "app/static/reports/1/new_report.md",
                "timestamp": "20261125120000",
            },
        }

    monkeypatch.setattr(
        lessonplan_analysis.LessonPlanAnalysisService,
        "analyze_lesson_plan",
        fake_analyze,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user(owner)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/lessonplan/analyze", json={"session_id": 1}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["report"] == "# 보고서"
        assert body["saved_report"] == {
            "filename": "new_report.md",
            "timestamp": "20261125120000",
        }
        assert "app/static/reports" not in resp.text
    finally:
        app.dependency_overrides.clear()


def test_openapi_has_no_report_path_fields():
    """#451: 공개 스키마와 예시에도 저장 경로 키가 남지 않는다."""
    schemas = app.openapi()["components"]["schemas"]
    for model, key in [
        ("AnalysisReportItem", "report_path"),
        ("SavedReportInfo", "file_path"),
    ]:
        assert key not in schemas[model]["properties"], model
        assert key not in schemas[model].get("required", []), model
    list_example = schemas["AnalysisReportListResponse"]["example"]
    for item in list_example["reports"]:
        assert "report_path" not in item
    analyze_example = schemas["LessonPlanAnalysisResponse"]["example"]
    assert "file_path" not in analyze_example["saved_report"]


@pytest.mark.asyncio
async def test_owner_can_read_and_download_report(parity_setup, tmp_path):
    """#451: DB의 경로는 그대로 쓰여 본인 상세·다운로드가 동작한다."""
    owner_id = parity_setup["owner_id"]
    report_file = tmp_path / "report1.md"
    report_file.write_text("# 제목\n\n본문 내용", encoding="utf-8")
    async with TestingSessionLocal() as db:
        owner = await db.get(User, owner_id)
        row = (
            await db.execute(
                select(AnalysisReport).where(
                    AnalysisReport.report_filename == "report1.md"
                )
            )
        ).scalar_one()
        row.report_path = str(report_file)
        await db.commit()
        report_id = row.id

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user(owner)
    try:
        with TestClient(app) as client:
            detail = client.get(f"/api/lessonplan/reports/{report_id}")
            download = client.get(
                f"/api/lessonplan/reports/{report_id}/download"
            )
        assert detail.status_code == 200
        assert detail.json()["content"] == "# 제목\n\n본문 내용"
        assert download.status_code == 200
        assert download.content == report_file.read_bytes()
        assert (
            'filename="report1.md"' in download.headers["content-disposition"]
        )
    finally:
        app.dependency_overrides.clear()
