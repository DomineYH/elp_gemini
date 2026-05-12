"""관리자 삭제 엔드포인트 통합 테스트."""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.dependencies import get_current_admin
from app.main import app
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.users import User
from app.utils.admin_csrf import ADMIN_CSRF_HEADER
from tests.conftest import (
    TestingSessionLocal,
    engine,
    override_admin,
    override_get_db,
)

_admin = User(
    id=999,
    username="admin",
    nickname="A",
    email="a@t.com",
    hashed_password="h",
    is_admin=True,
)


@pytest.fixture(autouse=True)
def _overrides():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_admin(_admin)
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seeded(db_tables, tmp_path):
    async with TestingSessionLocal() as db:
        # 테스트용 admin도 DB에 저장 (FK 무결성/감사 기록을 위해)
        admin_row = User(
            id=_admin.id,
            username=_admin.username,
            nickname=_admin.nickname,
            email=_admin.email,
            hashed_password="h",
            is_admin=True,
        )
        user = User(
            username="stu1",
            nickname="S1",
            email="s1@t.com",
            hashed_password="h",
            is_admin=False,
        )
        another_admin = User(
            username="admin2",
            nickname="A2",
            email="a2@t.com",
            hashed_password="h",
            is_admin=True,
        )
        db.add_all([admin_row, user, another_admin])
        await db.flush()

        session = ChatSession(user_id=user.id, user_type="1학년", title="A")
        db.add(session)
        await db.flush()
        db.add(ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content="hi",
        ))

        report_file = tmp_path / "r.md"
        report_file.write_text("x", encoding="utf-8")
        report = AnalysisReport(
            user_id=user.id,
            lessonplan_filename="",
            lessonplan_original_name="p.pdf",
            report_filename="r.md",
            report_path=str(report_file),
            latency_ms=1,
        )
        db.add(report)
        await db.commit()
        await db.refresh(user)
        await db.refresh(session)
        await db.refresh(report)
        await db.refresh(another_admin)

        yield {
            "user_id": user.id,
            "session_id": session.id,
            "report_id": report.id,
            "another_admin_id": another_admin.id,
            "report_file": report_file,
        }


def _get_token(client):
    """GET /admin/users 페이지를 통해 세션 CSRF 토큰을 발급/추출한다."""
    import re
    html = client.get("/admin/users").text
    m = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert m, "csrf-token meta missing"
    return m.group(1)


@pytest.mark.asyncio
async def test_delete_user_happy(seeded):
    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.delete(
            f"/admin/api/users/{seeded['user_id']}",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["deleted"] == 1


@pytest.mark.asyncio
async def test_delete_user_admin_target_forbidden(seeded):
    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.delete(
            f"/admin/api/users/{seeded['another_admin_id']}",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_self_forbidden(seeded):
    """현재 admin이 자기 자신을 지우려는 경우 403."""
    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.delete(
            f"/admin/api/users/{_admin.id}",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_csrf_required(seeded):
    with TestClient(app) as client:
        resp = client.delete(f"/admin/api/users/{seeded['user_id']}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_not_found(seeded):
    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.delete(
            "/admin/api/users/99999",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 404
