"""사용자 대시보드가 alias-or-title 값을 사용하는지 검증"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models.criteria import Criteria
from app.models.users import User
from app.main import app


@pytest_asyncio.fixture
async def db_session(tmp_path):
    """테스트용 DB 세션"""
    db_path = tmp_path / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def authed_client(db_session):
    """인증된 사용자 + DB 주입 TestClient"""
    user = User(
        username="testuser",
        nickname="Tester",
        email="test@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    async def _override_db():
        yield db_session

    def _override_user():
        return user

    from fastapi.testclient import TestClient

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[
        __import__(
            "app.dependencies", fromlist=["get_current_user"]
        ).get_current_user
    ] = _override_user
    client = TestClient(app, base_url="http://testserver")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dashboard_uses_alias_when_set(db_session, authed_client):
    c = Criteria(
        title="orig.pdf",
        file_size=100,
        uploaded_by="admin",
        file_path="/tmp/orig.pdf",
        status="active",
        display_alias="readable-name",
    )
    db_session.add(c)
    await db_session.commit()

    res = authed_client.get("/dashboard")
    assert res.status_code == 200
    assert "readable-name" in res.text


@pytest.mark.asyncio
async def test_dashboard_falls_back_to_title_when_alias_null(
    db_session, authed_client
):
    c = Criteria(
        title="fallback-doc.pdf",
        file_size=100,
        uploaded_by="admin",
        file_path="/tmp/fallback-doc.pdf",
        status="active",
        display_alias=None,
    )
    db_session.add(c)
    await db_session.commit()

    res = authed_client.get("/dashboard")
    assert res.status_code == 200
    assert "fallback-doc.pdf" in res.text


@pytest.mark.asyncio
async def test_dashboard_does_not_call_cloud(db_session, authed_client):
    """클라우드 호출이 제거되었는지 확인"""
    called = {"count": 0}

    async def fake_list(self):
        called["count"] += 1
        return []

    with patch(
        "app.services.criteria_vector_service.CriteriaVectorService"
        ".list_criteria_documents",
        fake_list,
    ):
        c = Criteria(
            title="x.pdf",
            file_size=10,
            uploaded_by="admin",
            file_path="/tmp/x.pdf",
            status="active",
        )
        db_session.add(c)
        await db_session.commit()

        authed_client.get("/dashboard")
        assert called["count"] == 0
