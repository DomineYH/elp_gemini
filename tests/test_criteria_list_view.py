"""평가기준 목록 뷰의 데이터 구조 테스트 (Wave 6)"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker,
)
from sqlalchemy.pool import StaticPool
from fastapi.templating import Jinja2Templates

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
    async def _make(**kwargs):
        defaults = dict(
            title="orig.pdf", file_size=10, uploaded_by="admin",
            file_path="/tmp/o.pdf", document_id=None, status="uploaded",
        )
        defaults.update(kwargs)
        alias = kwargs.get("display_alias")
        stable_id = kwargs.get("stable_id")
        save_kwargs = {
            k: v for k, v in defaults.items()
            if k not in ("display_alias", "stable_id")
        }
        async with admin_client._session_factory() as s:
            repo = CriteriaRepository(s)
            c = await repo.save_criteria(**save_kwargs)
            if alias is not None:
                await repo.update_display_alias(c.id, alias)
            if stable_id is not None:
                c.stable_id = stable_id
            await s.commit()
            return c
    return _make


@pytest.mark.asyncio
async def test_context_uses_criteria_items_list(
    admin_client, make_criteria
):
    """Wave 6: 컨텍스트는 criteria_items 리스트 + sync 만 노출한다."""
    c = await make_criteria(
        title="orig.pdf",
        document_id="cloud-doc-123",
        status="active",
        display_alias="my-alias",
        stable_id="01HSTABLE100",
    )

    captured = {}
    original_template = Jinja2Templates.TemplateResponse

    def capture(self, name, context, **kwargs):
        captured["context"] = context
        return original_template(self, name, context, **kwargs)

    import unittest.mock as _m
    with _m.patch.object(Jinja2Templates, "TemplateResponse", capture):
        res = await admin_client.get("/admin/criteria")

    assert res.status_code == 200
    ctx = captured["context"]

    # criteria_items 가 노출되어야 함
    assert "criteria_items" in ctx
    items = ctx["criteria_items"]
    assert isinstance(items, list)
    assert len(items) == 1
    item = items[0]
    assert item["stable_id"] == "01HSTABLE100"
    assert item["title"] == "orig.pdf"
    assert item["display_alias"] == "my-alias"
    assert item["status"] == "active"
    assert item["document_id"] == "cloud-doc-123"
    assert "created_at" in item

    # sync 메타데이터 노출
    assert "sync" in ctx

    # Wave 5 이전 키들은 제거되어야 함
    for removed in (
        "cloud_documents",
        "cloud_error",
        "needs_sync",
        "pending_count",
        "cloud_sync_warning",
        "active_criteria",
    ):
        assert removed not in ctx, f"{removed} 가 컨텍스트에 남아있음"

    # 응답 본문에도 c.id 의 흔적 (이전 dual-table)이 남으면 안 됨
    assert "클라우드 Store 문서" not in res.text


@pytest.mark.asyncio
async def test_criteria_items_skip_null_stable_id(
    admin_client, make_criteria
):
    """stable_id 가 None 인 행은 criteria_items 에 포함되지 않는다."""
    await make_criteria(
        title="legacy.pdf", status="uploaded",
        # stable_id 미설정
    )
    await make_criteria(
        title="modern.pdf", status="uploaded",
        stable_id="01HSTABLE200",
    )

    captured = {}
    original_template = Jinja2Templates.TemplateResponse

    def capture(self, name, context, **kwargs):
        captured["context"] = context
        return original_template(self, name, context, **kwargs)

    import unittest.mock as _m
    with _m.patch.object(Jinja2Templates, "TemplateResponse", capture):
        res = await admin_client.get("/admin/criteria")

    assert res.status_code == 200
    items = captured["context"]["criteria_items"]
    assert len(items) == 1
    assert items[0]["title"] == "modern.pdf"
    assert items[0]["stable_id"] == "01HSTABLE200"
