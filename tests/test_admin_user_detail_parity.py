"""
Parity invariant: a user's dashboard endpoints and the admin per-user endpoints
must return the same set of sessions and reports when looking at the same user.
"""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, get_db
from app.dependencies import get_current_admin, get_current_user
from app.models.users import User
from app.models.chat_sessions import ChatSession
from app.models.chat_messages import ChatMessage, MessageRole
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
        db.add(ChatMessage(
            session_id=s1.id,
            role=MessageRole.USER,
            content="최근 메시지",
            created_at=base_time + timedelta(hours=2),
        ))

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
            admin_resp = client.get(f"/admin/api/users/{owner_id}/sessions?limit=50&offset=0")
        assert user_resp.status_code == 200
        assert admin_resp.status_code == 200
        user_ids = [s["session_id"] for s in user_resp.json()["sessions"]]
        admin_ids = [s["session_id"] for s in admin_resp.json()["sessions"]]
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
        user_ids = [r["id"] for r in user_resp.json()["reports"]]
        admin_ids = [r["id"] for r in admin_resp.json()["reports"]]
        assert user_ids == admin_ids
    finally:
        app.dependency_overrides.clear()
