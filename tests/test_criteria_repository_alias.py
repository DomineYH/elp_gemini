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
    c1 = await repo.save_criteria(
        title="a.pdf",
        file_size=1,
        uploaded_by="admin",
        file_path="/tmp/a.pdf",
        document_id="doc-aaa",
        status="active",
    )
    c2 = await repo.save_criteria(
        title="b.pdf",
        file_size=1,
        uploaded_by="admin",
        file_path="/tmp/b.pdf",
        document_id="doc-bbb",
        status="active",
    )
    await db_session.commit()

    mapping = await repo.get_criteria_map_by_document_ids(
        ["doc-aaa", "doc-bbb", "doc-missing"]
    )
    assert mapping["doc-aaa"].id == c1.id
    assert mapping["doc-aaa"].title == "a.pdf"
    assert mapping["doc-bbb"].id == c2.id
    assert "doc-missing" not in mapping


@pytest.mark.asyncio
async def test_get_criteria_map_empty_input(db_session):
    repo = CriteriaRepository(db_session)
    assert await repo.get_criteria_map_by_document_ids([]) == {}
