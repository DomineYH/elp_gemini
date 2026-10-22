"""QnA document chat sessions get a human title, keyed by document_id (#175)."""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies import get_current_user
from app.migrations.chat_sessions_document_id import (
    ensure_chat_sessions_document_id_column,
)
from app.models.chat_sessions import ChatSession
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from app.routers import qna

DOC = "fileSearchStores/s1/documents/d1"

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    async with SessionLocal() as database:
        yield database


@pytest_asyncio.fixture
async def user():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        row = User(
            username="title_user",
            nickname="Title User",
            hashed_password="hashed",
            is_admin=False,
        )
        db.add(row)
        await db.commit()
    yield row
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(user):
    test_app = FastAPI()
    test_app.include_router(qna.router)
    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_user] = lambda: user
    answer = {"question": "q", "answer": "a", "latency_ms": 1}
    with patch(
        "app.services.qna_service.QnAService.ask_question",
        AsyncMock(return_value=answer),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as async_client:
            yield async_client


async def _ask(client):
    response = await client.post(f"/api/qna/{DOC}", json={"question": "질문"})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


async def _sessions():
    async with SessionLocal() as db:
        return (await db.execute(select(ChatSession))).scalars().all()


@pytest.mark.asyncio
async def test_new_session_uses_upload_filename_and_is_reused(client, user):
    async with SessionLocal() as db:
        db.add(
            LessonPlanUpload(
                user_id=user.id,
                filename="title_user_lesson.pdf",
                original_filename="lesson.pdf",
            )
        )
        await db.commit()

    first = await _ask(client)
    second = await _ask(client)

    sessions = await _sessions()
    assert first == second
    assert len(sessions) == 1
    assert sessions[0].title == "lesson.pdf"
    assert sessions[0].document_id == DOC


@pytest.mark.asyncio
async def test_without_upload_title_is_fixed_label(client):
    await _ask(client)

    sessions = await _sessions()
    assert [s.title for s in sessions] == ["업로드한 지도안"]
    assert "d1" not in sessions[0].title


@pytest.mark.asyncio
async def test_legacy_session_is_reused_after_backfill(client, user):
    async with SessionLocal() as db:
        legacy = ChatSession(user_id=user.id, title=DOC, user_type="교사")
        db.add(legacy)
        await db.commit()
    await ensure_chat_sessions_document_id_column(engine)

    session_id = await _ask(client)

    sessions = await _sessions()
    assert session_id == legacy.id
    assert len(sessions) == 1
    assert sessions[0].document_id == DOC
    assert sessions[0].title == "업로드한 지도안"
    response = await client.get("/api/qna/sessions")
    assert response.status_code == 200, response.text
    listed = response.json()["sessions"]
    assert [s["title"] for s in listed] == ["업로드한 지도안"]
    assert "fileSearchStores/" not in response.text
