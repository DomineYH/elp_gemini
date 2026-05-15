"""CriteriaRepository — stable_id lookup 헬퍼"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.migrations.criteria_stable_id import ensure_criteria_stable_id_column
from app.models.criteria import Criteria
from app.repositories.criteria_repository import CriteriaRepository


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_criteria_stable_id_column(engine)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest.mark.asyncio
async def test_get_by_stable_id_returns_row(session):
    session.add(Criteria(
        title="t.pdf", document_id="d1", file_size=10, file_path="x",
        status="uploaded", uploaded_by="admin", stable_id="01HSID",
    ))
    await session.commit()

    repo = CriteriaRepository(session)
    row = await repo.get_criteria_by_stable_id("01HSID")
    assert row is not None
    assert row.title == "t.pdf"


@pytest.mark.asyncio
async def test_get_by_stable_id_returns_none_for_missing(session):
    repo = CriteriaRepository(session)
    assert await repo.get_criteria_by_stable_id("nope") is None


@pytest.mark.asyncio
async def test_truncate_clears_all_rows(session):
    session.add(Criteria(
        title="a.pdf", document_id="d2", file_size=10, file_path="x",
        status="uploaded", uploaded_by="admin", stable_id="01HA",
    ))
    await session.commit()
    repo = CriteriaRepository(session)
    await repo.truncate()
    await session.commit()
    assert await repo.get_criteria_by_stable_id("01HA") is None
