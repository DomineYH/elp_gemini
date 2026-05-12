"""CriteriaRepository alias 메서드 테스트"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.criteria import Criteria
from app.repositories.criteria_repository import CriteriaRepository


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


@pytest.mark.asyncio
async def test_update_display_alias_sets_value(db_session):
    repo = CriteriaRepository(db_session)
    criteria = await repo.save_criteria(
        title="test.pdf",
        file_size=100,
        uploaded_by="admin",
        file_path="/tmp/test.pdf",
    )
    await db_session.commit()

    updated = await repo.update_display_alias(criteria.id, "수학 평가기준")
    assert updated is not None
    assert updated.display_alias == "수학 평가기준"


@pytest.mark.asyncio
async def test_update_display_alias_returns_none_for_missing(db_session):
    repo = CriteriaRepository(db_session)
    result = await repo.update_display_alias(9999, "없는 값")
    assert result is None


@pytest.mark.asyncio
async def test_get_criteria_map_by_document_ids(db_session):
    repo = CriteriaRepository(db_session)

    c1 = Criteria(
        title="a.pdf",
        file_size=10,
        uploaded_by="admin",
        file_path="/a.pdf",
        document_id="doc-1",
        status="active",
        display_alias="별명A",
    )
    c2 = Criteria(
        title="b.pdf",
        file_size=20,
        uploaded_by="admin",
        file_path="/b.pdf",
        document_id="doc-2",
        status="active",
        display_alias=None,
    )
    db_session.add_all([c1, c2])
    await db_session.commit()

    mapping = await repo.get_criteria_map_by_document_ids(
        ["doc-1", "doc-2"]
    )
    assert mapping == {
        "doc-1": {"id": c1.id, "name": "별명A"},
        "doc-2": {"id": c2.id, "name": "b.pdf"},
    }


@pytest.mark.asyncio
async def test_get_criteria_map_skips_unknown_ids(db_session):
    repo = CriteriaRepository(db_session)
    mapping = await repo.get_criteria_map_by_document_ids(
        ["nonexistent"]
    )
    assert mapping == {}
