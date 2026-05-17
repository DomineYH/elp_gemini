"""E2E test fixtures for criteria multi-active tests."""
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies import get_current_admin
from app.main import app
from app.models.users import User


@pytest_asyncio.fixture
async def e2e_client(tmp_path):
    """Fresh SQLite DB + httpx AsyncClient with admin auth."""
    db_path = tmp_path / "e2e_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sf = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    async def override_get_db():
        async with sf() as session:
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


@pytest_asyncio.fixture
async def db_session(e2e_client, tmp_path):
    """DB session for assertions (shares DB file with e2e_client)."""
    db_path = tmp_path / "e2e_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sf = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with sf() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def fake_vector_client():
    """Mock CriteriaVectorService with sensible defaults."""
    vec = MagicMock()
    vec.file_search_service.client = MagicMock()
    vec.list_criteria_documents = AsyncMock(return_value=[])
    vec.upload_criteria = AsyncMock(return_value={"document_id": "docs/fake1"})
    vec.delete_criteria = AsyncMock(return_value=True)
    return vec
