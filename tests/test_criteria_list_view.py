"""평가기준 목록 뷰의 데이터 보강 테스트"""
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
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

    app.dependency_overrides.clear()
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
        async with admin_client._session_factory() as s:
            repo = CriteriaRepository(s)
            c = await repo.save_criteria(
                **{k: v for k, v in defaults.items() if k != "display_alias"}
            )
            if alias is not None:
                await repo.update_display_alias(c.id, alias)
            await s.commit()
            return c
    return _make


@pytest.mark.asyncio
async def test_cloud_docs_enriched_in_context(
    admin_client, make_criteria
):
    c = await make_criteria(
        title="orig.pdf",
        document_id="cloud-doc-123",
        status="active",
        display_alias="my-alias",
    )

    fake_list = AsyncMock(return_value=[
        {"document_id": "cloud-doc-123", "display_name": "orig_pdf"},
        {"document_id": "cloud-doc-orphan", "display_name": "orphan_pdf"},
    ])

    captured = {}
    original_template = Jinja2Templates.TemplateResponse

    def capture(self, name, context, **kwargs):
        captured["context"] = context
        return original_template(self, name, context, **kwargs)

    with patch(
        "app.routers.admin.criteria_views.CriteriaVectorService"
        ".list_criteria_documents",
        fake_list,
    ), patch.object(
        Jinja2Templates, "TemplateResponse", capture
    ):
        res = await admin_client.get("/admin/criteria")

    assert res.status_code == 200
    ctx = captured["context"]

    # 상단 표 데이터에 display_alias 노출
    top_doc = ctx["criteria"]["documents"][0]
    assert top_doc["display_alias"] == "my-alias"

    # 하단 클라우드 표 enrichment
    cloud_docs = ctx["cloud_documents"]
    matched = next(
        d for d in cloud_docs
        if d["document_id"] == "cloud-doc-123"
    )
    assert matched["title"] == "orig.pdf"
    assert matched["alias"] == "my-alias"
    assert matched["criteria_id"] == c.id

    orphan = next(
        d for d in cloud_docs
        if d["document_id"] == "cloud-doc-orphan"
    )
    assert orphan["title"] is None
    assert orphan["alias"] is None
    assert orphan["criteria_id"] is None


@pytest.mark.asyncio
async def test_top_table_exposes_display_alias_for_all_criteria(
    admin_client, make_criteria
):
    """상단 표의 모든 항목에 display_alias 필드가 있어야 함"""
    await make_criteria(
        title="no-alias.pdf",
        status="uploaded",
    )
    await make_criteria(
        title="has-alias.pdf",
        status="uploaded",
        display_alias="nice-name",
    )

    fake_list = AsyncMock(return_value=[])

    captured = {}
    original_template = Jinja2Templates.TemplateResponse

    def capture(self, name, context, **kwargs):
        captured["context"] = context
        return original_template(self, name, context, **kwargs)

    with patch(
        "app.routers.admin.criteria_views.CriteriaVectorService"
        ".list_criteria_documents",
        fake_list,
    ), patch.object(
        Jinja2Templates, "TemplateResponse", capture
    ):
        res = await admin_client.get("/admin/criteria")

    assert res.status_code == 200
    docs = captured["context"]["criteria"]["documents"]
    assert len(docs) == 2
    # display_alias 필드가 존재해야 함 (None이더라도)
    for doc in docs:
        assert "display_alias" in doc
