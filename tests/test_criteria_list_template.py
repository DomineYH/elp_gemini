"""criteria_list 템플릿 렌더링 검증 (Wave 6: 단일 테이블)"""
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
async def test_template_renders_empty_state(admin_client):
    """평가기준이 없으면 안내 문구가 출력된다."""
    res = await admin_client.get("/admin/criteria")
    assert res.status_code == 200
    assert "평가 기준이 없습니다" in res.text


@pytest.mark.asyncio
async def test_template_has_single_table_with_alias_cell_and_active_radio(
    admin_client,
):
    """Wave 6 단일 테이블: alias-cell + active-radio 가 행마다 렌더된다."""
    async with admin_client._session_factory() as s:
        repo = CriteriaRepository(s)
        c = await repo.save_criteria(
            title="orig.pdf", file_size=1, uploaded_by="admin",
            file_path="/tmp/o.pdf", document_id="doc-1",
            status="active",
        )
        # stable_id 부여 (Wave 6: stable_id 있는 행만 표시)
        c.stable_id = "01HSTABLE001"
        await repo.update_display_alias(c.id, "my-alias")
        await s.commit()

    res = await admin_client.get("/admin/criteria")
    text = res.text
    assert res.status_code == 200

    # 단일 테이블 UI 마커
    assert 'class="alias-cell' in text
    assert 'class="active-radio' in text

    # alias 값 + stable_id 데이터가 행에 들어가야 함
    assert "my-alias" in text
    assert "01HSTABLE001" in text
    # 상태 라벨
    assert "활성" in text

    # 제거된 dual-table / 동기화 확정 잔재가 없어야 함
    assert "클라우드 Store 문서" not in text
    assert "동기화 확정" not in text
    assert "(매칭 없음)" not in text


@pytest.mark.asyncio
async def test_template_skips_rows_without_stable_id(admin_client):
    """stable_id가 NULL인 pre-reconcile 행은 목록에 노출되지 않는다."""
    async with admin_client._session_factory() as s:
        repo = CriteriaRepository(s)
        await repo.save_criteria(
            title="legacy.pdf", file_size=1, uploaded_by="admin",
            file_path="/tmp/legacy.pdf", document_id=None,
            status="uploaded",
        )
        await s.commit()

    res = await admin_client.get("/admin/criteria")
    assert res.status_code == 200
    # stable_id 없는 row 의 title은 목록 행으로 나오면 안 됨 → empty state 노출
    assert "legacy.pdf" not in res.text
    assert "평가 기준이 없습니다" in res.text


@pytest.mark.asyncio
async def test_template_alias_unset_placeholder(admin_client):
    """display_alias 가 None 인 경우 '(미설정)' 플레이스홀더가 출력된다."""
    async with admin_client._session_factory() as s:
        repo = CriteriaRepository(s)
        c = await repo.save_criteria(
            title="no-alias.pdf", file_size=1, uploaded_by="admin",
            file_path="/tmp/n.pdf", document_id="doc-x",
            status="uploaded",
        )
        c.stable_id = "01HSTABLE002"
        await s.commit()

    res = await admin_client.get("/admin/criteria")
    assert res.status_code == 200
    assert "(미설정)" in res.text
    # uploaded 상태 → "비활성" 라벨
    assert "비활성" in res.text
