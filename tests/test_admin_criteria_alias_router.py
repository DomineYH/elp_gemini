"""PATCH /api/admin/criteria/{id}/display-alias 테스트"""
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


@pytest_asyncio.fixture
async def make_criteria(admin_client):
    """admin_client의 session으로 Criteria row를 만들어 반환"""
    async def _make(**kwargs):
        defaults = dict(
            title="orig.pdf", file_size=10, uploaded_by="admin",
            file_path="/tmp/o.pdf", document_id=None, status="uploaded",
        )
        defaults.update(kwargs)
        async with admin_client._session_factory() as s:
            repo = CriteriaRepository(s)
            c = await repo.save_criteria(**defaults)
            await s.commit()
            return c
    return _make


@pytest.mark.asyncio
async def test_patch_alias_success(admin_client, make_criteria):
    c = await make_criteria()
    res = await admin_client.patch(
        f"/api/admin/criteria/{c.id}/display-alias",
        json={"display_alias": "math-grade-6"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["criteria_id"] == c.id
    assert body["display_alias"] == "math-grade-6"


@pytest.mark.asyncio
async def test_patch_alias_clears_with_null(admin_client, make_criteria):
    c = await make_criteria()
    await admin_client.patch(
        f"/api/admin/criteria/{c.id}/display-alias",
        json={"display_alias": "tmp"},
    )
    res = await admin_client.patch(
        f"/api/admin/criteria/{c.id}/display-alias",
        json={"display_alias": None},
    )
    assert res.status_code == 200
    assert res.json()["display_alias"] is None


@pytest.mark.asyncio
async def test_patch_alias_not_found(admin_client):
    res = await admin_client.patch(
        "/api/admin/criteria/99999/display-alias",
        json={"display_alias": "x"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_patch_alias_accepts_korean(admin_client, make_criteria):
    """한글 alias가 정상적으로 저장·반환되는지 검증"""
    c = await make_criteria()
    res = await admin_client.patch(
        f"/api/admin/criteria/{c.id}/display-alias",
        json={"display_alias": "수학 평가기준"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["display_alias"] == "수학 평가기준"


@pytest.mark.asyncio
async def test_patch_alias_rejects_control_chars(
    admin_client, make_criteria
):
    c = await make_criteria()
    res = await admin_client.patch(
        f"/api/admin/criteria/{c.id}/display-alias",
        json={"display_alias": "a\x00b"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_alias_forbidden_for_non_admin(admin_client, make_criteria):
    """비관리자 사용자가 PATCH 호출 시 401/403 반환을 검증"""
    from fastapi import HTTPException, status

    c = await make_criteria()

    def deny_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not admin",
        )

    original_admin = app.dependency_overrides.pop(get_current_admin, None)
    app.dependency_overrides[get_current_admin] = deny_admin
    try:
        res = await admin_client.patch(
            f"/api/admin/criteria/{c.id}/display-alias",
            json={"display_alias": "x"},
        )
        assert res.status_code in (401, 403)
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        if original_admin is not None:
            app.dependency_overrides[get_current_admin] = original_admin
