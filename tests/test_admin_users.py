"""
관리자 사용자 관리 API 테스트
통계, 세션 목록, 세션 상세 엔드포인트 검증
"""
import pytest
import pytest_asyncio
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
