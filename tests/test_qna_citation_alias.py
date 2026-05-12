"""QnA citation에 alias가 반영되는지 검증"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.criteria import Criteria
from app.services.criteria_context_service import CriteriaContextService


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
async def test_citation_uses_alias_when_set(db_session):
    c = Criteria(
        title="lesson-criteria.pdf",
        file_size=100,
        uploaded_by="admin",
        file_path="/tmp/lesson-criteria.pdf",
        status="active",
        display_alias="readable-criterion",
    )
    db_session.add(c)
    await db_session.commit()

    service = CriteriaContextService(db=db_session)
    fake_search = AsyncMock(return_value={
        "response_text": "answer",
        "citations": [{"title": "lesson-criteria.pdf", "uri": "..."}],
        "sources_count": 1,
    })
    with patch.object(service.vector_service, "search_criteria", fake_search):
        result = await service.get_context("question")

    assert len(result["criteria_metadata"]) == 1
    assert result["criteria_metadata"][0]["title"] == "readable-criterion"


@pytest.mark.asyncio
async def test_citation_falls_back_when_alias_null(db_session):
    c = Criteria(
        title="raw-title.pdf",
        file_size=100,
        uploaded_by="admin",
        file_path="/tmp/raw-title.pdf",
        status="active",
        display_alias=None,
    )
    db_session.add(c)
    await db_session.commit()

    service = CriteriaContextService(db=db_session)
    fake_search = AsyncMock(return_value={
        "response_text": "answer",
        "citations": [{"title": "raw-title.pdf"}],
        "sources_count": 1,
    })
    with patch.object(service.vector_service, "search_criteria", fake_search):
        result = await service.get_context("question")

    assert result["criteria_metadata"][0]["title"] == "raw-title.pdf"
