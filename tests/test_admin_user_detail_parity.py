"""
Parity invariant: a user's dashboard endpoints and the admin per-user endpoints
must return the same set of sessions and reports when looking at the same user.
Also confirms that User.email is the identity key (same email → same user_id).
"""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, get_db
from app.dependencies import get_current_admin, get_current_user
from app.models.users import User
from app.models.chat_sessions import ChatSession
from app.models.analysis_reports import AnalysisReport
from tests.conftest import (
    TestingSessionLocal,
    override_get_db,
    override_admin,
    engine,
)


_admin = User(
    id=999,
    username="parity_admin",
    nickname="ParityAdmin",
    email="parity_admin@test.com",
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
            email="parity_user@test.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add(owner)
        await db.flush()

        s1 = ChatSession(user_id=owner.id, user_type="1학년", title="대화1")
        s2 = ChatSession(user_id=owner.id, user_type="2학년", title="대화2")
        db.add_all([s1, s2])

        r1 = AnalysisReport(
            user_id=owner.id,
            lessonplan_filename="lp1.pdf",
            lessonplan_original_name="지도안1.pdf",
            report_filename="report1.md",
            report_path="/tmp/report1.md",
            latency_ms=1000,
        )
        r2 = AnalysisReport(
            user_id=owner.id,
            lessonplan_filename="lp2.pdf",
            lessonplan_original_name="지도안2.pdf",
            report_filename="report2.md",
            report_path="/tmp/report2.md",
            latency_ms=1200,
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
            admin_resp = client.get(f"/admin/api/users/{owner_id}/sessions?limit=50&offset=0")
        assert user_resp.status_code == 200
        assert admin_resp.status_code == 200
        user_ids = sorted(s["session_id"] for s in user_resp.json()["sessions"])
        admin_ids = sorted(s["session_id"] for s in admin_resp.json()["sessions"])
        assert user_ids == admin_ids
        assert user_resp.json()["total_count"] == admin_resp.json()["total_count"]
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
            admin_resp = client.get(f"/admin/api/users/{owner_id}/reports?limit=100&offset=0")
        assert user_resp.status_code == 200
        assert admin_resp.status_code == 200
        user_ids = sorted(r["id"] for r in user_resp.json()["reports"])
        admin_ids = sorted(r["id"] for r in admin_resp.json()["reports"])
        assert user_ids == admin_ids
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_same_email_resolves_to_same_user_id(parity_setup):
    """이메일 정규화로 같은 이메일은 같은 user_id를 가리킨다."""
    from app.services.auth_service import AuthService
    owner_id = parity_setup["owner_id"]
    async with TestingSessionLocal() as db:
        svc = AuthService(db)
        found_lower = await svc.get_user_by_email("parity_user@test.com")
        found_upper = await svc.get_user_by_email("PARITY_USER@TEST.COM")
    assert found_lower is not None
    assert found_upper is not None
    assert found_lower.id == owner_id
    assert found_upper.id == owner_id
