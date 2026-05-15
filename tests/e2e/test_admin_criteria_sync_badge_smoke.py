"""T8: criteria_list 템플릿 동기화 배지 렌더링 검증"""
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies import get_current_admin
from app.models.users import User


@pytest_asyncio.fixture
async def admin_client(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_get_admin():
        return User(id=1, username="admin", email="a@b.c", is_admin=True)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_get_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_admin, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_badge_renders_ok(admin_client):
    fake_sync = AsyncMock(
        return_value={
            "state": "ok",
            "last_synced_at": "2026-05-15T00:00Z",
            "error": None,
        },
    )
    fake_cloud = AsyncMock(return_value=[])
    with (
        patch(
            "app.routers.admin.criteria_views._fetch_sync_metadata",
            fake_sync,
        ),
        patch(
            "app.routers.admin.criteria_views.CriteriaVectorService"
            ".list_criteria_documents",
            fake_cloud,
        ),
    ):
        res = await admin_client.get("/admin/criteria")
    assert res.status_code == 200
    assert "동기화 완료" in res.text


@pytest.mark.asyncio
async def test_badge_renders_error_with_disabled_buttons(admin_client):
    fake_sync = AsyncMock(
        return_value={
            "state": "error",
            "last_synced_at": None,
            "error": "network down",
        },
    )
    fake_cloud = AsyncMock(return_value=[])
    with (
        patch(
            "app.routers.admin.criteria_views._fetch_sync_metadata",
            fake_sync,
        ),
        patch(
            "app.routers.admin.criteria_views.CriteriaVectorService"
            ".list_criteria_documents",
            fake_cloud,
        ),
    ):
        res = await admin_client.get("/admin/criteria")
    assert res.status_code == 200
    assert "동기화 실패" in res.text
    assert 'data-disabled-when="not-ok"' in res.text
