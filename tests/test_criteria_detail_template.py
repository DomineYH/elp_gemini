"""criteria_detail 템플릿 렌더링 검증"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies import get_current_admin
from app.repositories.criteria_repository import CriteriaRepository
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
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_get_admin():
        return User(
            id=1, username="admin", email="a@b.c", is_admin=True
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_get_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        client._session_factory = session_factory
        yield client

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_admin, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_detail_shows_display_alias(admin_client):
    async with admin_client._session_factory() as s:
        repo = CriteriaRepository(s)
        c = await repo.save_criteria(
            title="orig.pdf", file_size=1, uploaded_by="admin",
            file_path="/tmp/o.pdf", document_id=None,
            status="active",
        )
        await repo.update_display_alias(c.id, "detail-alias")
        await s.commit()
    res = await admin_client.get(f"/admin/criteria/{c.id}")
    assert res.status_code == 200
    assert "표시명: detail-alias" in res.text


@pytest.mark.asyncio
async def test_detail_hides_alias_line_when_null(admin_client):
    async with admin_client._session_factory() as s:
        repo = CriteriaRepository(s)
        c = await repo.save_criteria(
            title="orig.pdf", file_size=1, uploaded_by="admin",
            file_path="/tmp/o.pdf", document_id=None,
            status="active",
        )
        await s.commit()
    res = await admin_client.get(f"/admin/criteria/{c.id}")
    assert res.status_code == 200
    assert "표시명:" not in res.text
