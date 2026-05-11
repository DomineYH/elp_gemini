"""
관리자 사용자 관리 API 테스트
통계, 세션 목록, 세션 상세 엔드포인트 검증
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException, status as http_status
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.models.chat_sessions import ChatSession
from app.models.chat_messages import (
    ChatMessage,
    MessageRole,
)
from app.models.analysis_reports import AnalysisReport
from tests.conftest import (
    TestingSessionLocal,
    override_get_db,
    override_admin,
    engine,
)

# 테스트용 관리자 (DB 미저장, 의존성 오버라이드용)
_admin = User(
    id=999,
    username="test_admin",
    nickname="TestAdmin",
    email="tadmin@test.com",
    hashed_password="hashed",
    is_admin=True,
)


@pytest.fixture(autouse=True)
def _override_deps():
    """의존성 오버라이드"""
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = (
        override_admin(_admin)
    )
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_tables():
    """DB 테이블 생성/삭제"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seed_data(db_tables):
    """테스트 데이터 시드"""
    async with TestingSessionLocal() as db:
        user = User(
            username="stu1",
            nickname="Student1",
            email="stu1@test.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add(user)
        await db.flush()

        s1 = ChatSession(
            user_id=user.id,
            user_type="1학년",
            title="세션A",
        )
        s2 = ChatSession(
            user_id=user.id,
            user_type="2학년",
            title="세션B",
        )
        db.add_all([s1, s2])
        await db.flush()

        m1 = ChatMessage(
            session_id=s1.id,
            role=MessageRole.USER,
            content="질문입니다",
        )
        m2 = ChatMessage(
            session_id=s1.id,
            role=MessageRole.ASSISTANT,
            content="답변입니다",
            model_name="gemini-2.5-flash",
            citations=[{"title": "참고"}],
        )
        db.add_all([m1, m2])

        rpt = AnalysisReport(
            user_id=user.id,
            lessonplan_filename="lp.pdf",
            lessonplan_original_name="원본.pdf",
            report_filename="rpt.md",
            report_path="/reports/rpt.md",
            latency_ms=1200,
        )
        db.add(rpt)
        await db.commit()

        await db.refresh(s1)
        await db.refresh(s2)

        yield {
            "user": user,
            "sessions": [s1, s2],
            "session1_id": s1.id,
        }


@pytest.mark.asyncio
async def test_stats_returns_counts(seed_data):
    """stats API가 학년별 데이터 반환"""
    with TestClient(app) as client:
        resp = client.get("/admin/api/users/stats")
    assert resp.status_code == 200

    data = resp.json()
    assert "stats" in data
    assert "totals" in data
    assert len(data["stats"]) == 5

    grade1 = next(
        s for s in data["stats"]
        if s["user_type"] == "1학년"
    )
    assert grade1["session_count"] == 1
    assert grade1["qna_count"] >= 1

    totals = data["totals"]
    assert totals["session_count"] >= 2


@pytest.mark.asyncio
async def test_sessions_list_paginated(seed_data):
    """세션 목록 페이징"""
    with TestClient(app) as client:
        resp = client.get(
            "/admin/api/users/sessions"
            "?page=1&page_size=10"
        )
    assert resp.status_code == 200

    data = resp.json()
    assert "sessions" in data
    assert "total" in data
    assert data["total"] >= 2
    assert data["page"] == 1
    assert data["page_size"] == 10

    sess = data["sessions"][0]
    assert "session_id" in sess
    assert "user_type" in sess
    assert "qna_count" in sess
    assert "message_count" in sess
    assert "last_activity" in sess
    assert "status" in sess


@pytest.mark.asyncio
async def test_sessions_filter_by_user_type(seed_data):
    """user_type 필터"""
    with TestClient(app) as client:
        resp = client.get(
            "/admin/api/users/sessions?user_type=1학년"
        )
    assert resp.status_code == 200

    data = resp.json()
    for sess in data["sessions"]:
        assert sess["user_type"] == "1학년"
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_session_detail_with_messages(seed_data):
    """상세 API가 메시지+보고서 반환"""
    sid = seed_data["session1_id"]
    with TestClient(app) as client:
        resp = client.get(
            f"/admin/api/users/session/{sid}"
        )
    assert resp.status_code == 200

    data = resp.json()
    assert data["session_id"] == sid
    assert data["user_type"] == "1학년"
    assert len(data["messages"]) == 2
    assert len(data["reports"]) >= 1

    msg = data["messages"][0]
    assert "id" in msg
    assert "role" in msg
    assert "content" in msg
    assert "created_at" in msg

    rpt = data["reports"][0]
    assert "id" in rpt
    assert "filename" in rpt
    assert "report_path" in rpt


@pytest.mark.asyncio
async def test_session_detail_not_found(db_tables):
    """존재하지 않는 세션 → 404"""
    with TestClient(app) as client:
        resp = client.get(
            "/admin/api/users/session/99999"
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_report_detail_happy(seed_data, tmp_path):
    """관리자가 임의 사용자의 보고서 조회 (소유권 우회)"""
    content_text = "# Hello\n관리자 보고서 본문\n"
    report_file = tmp_path / "rpt2.md"
    report_file.write_text(content_text, encoding="utf-8")

    async with TestingSessionLocal() as db:
        rpt = AnalysisReport(
            user_id=seed_data["user"].id,
            lessonplan_filename="lp2.pdf",
            lessonplan_original_name="원본2.pdf",
            report_filename="rpt2.md",
            report_path=str(report_file),
            latency_ms=2200,
        )
        db.add(rpt)
        await db.commit()
        await db.refresh(rpt)
        rpt_id = rpt.id

    with TestClient(app) as client:
        resp = client.get(f"/admin/api/reports/{rpt_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == rpt_id
    assert data["report_filename"] == "rpt2.md"
    assert data["lessonplan_filename"] == "lp2.pdf"
    assert data["lessonplan_original_name"] == "원본2.pdf"
    assert data["latency_ms"] == 2200
    assert data["content"] == content_text
    assert data["content"].startswith("# Hello")


@pytest.mark.asyncio
async def test_admin_report_detail_row_missing(db_tables):
    """존재하지 않는 보고서 ID → 404"""
    with TestClient(app) as client:
        resp = client.get("/admin/api/reports/999999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "보고서를 찾을 수 없습니다."


@pytest.mark.asyncio
async def test_admin_report_detail_file_missing(db_tables):
    """DB 행은 있으나 파일이 디스크에 없음 → 404"""
    async with TestingSessionLocal() as db:
        user = User(
            username="ghost",
            nickname="Ghost",
            email="ghost@test.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add(user)
        await db.flush()
        rpt = AnalysisReport(
            user_id=user.id,
            lessonplan_filename="lp.pdf",
            lessonplan_original_name="원본.pdf",
            report_filename="rpt.md",
            report_path="/nonexistent/__no__/missing.md",
            latency_ms=0,
        )
        db.add(rpt)
        await db.commit()
        await db.refresh(rpt)
        rpt_id = rpt.id

    with TestClient(app) as client:
        resp = client.get(f"/admin/api/reports/{rpt_id}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "보고서 파일이 존재하지 않습니다."


@pytest.mark.asyncio
async def test_admin_report_detail_forbidden_for_non_admin(db_tables):
    """비관리자 호출 시 403"""
    def _deny_admin():
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )

    app.dependency_overrides[get_current_admin] = _deny_admin
    try:
        with TestClient(app) as client:
            resp = client.get("/admin/api/reports/1")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "관리자 권한이 필요합니다."
    finally:
        # 본 테스트 내 다른 단언이 추가되더라도 안전하도록 admin 오버라이드 복원
        app.dependency_overrides[get_current_admin] = (
            override_admin(_admin)
        )


@pytest.mark.asyncio
async def test_admin_report_viewer_page_renders(db_tables):
    """뷰어 HTML 페이지 렌더링: JS 상수와 API URL 포함"""
    with TestClient(app) as client:
        resp = client.get("/admin/reports/view/1")
    assert resp.status_code == 200
    body = resp.text
    assert "REPORT_ID = 1" in body
    assert "/admin/api/reports/" in body


@pytest.mark.asyncio
async def test_admin_report_viewer_rejects_non_positive_id(db_tables):
    """뷰어가 0/음수 id를 404로 거부"""
    with TestClient(app) as client:
        resp = client.get("/admin/reports/view/0")
    assert resp.status_code == 404
