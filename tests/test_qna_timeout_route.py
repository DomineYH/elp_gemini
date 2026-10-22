"""Gemini 타임아웃은 504로 알리고 빈 자동 세션을 남기지 않는다 (#218)"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import Base, get_db
from app.dependencies import get_current_user
from app.models.chat_sessions import ChatSession
from app.models.users import User
from app.routers import qna
from tests.test_qna_session_title import (
    DOC,
    SessionLocal,
    engine,
    override_get_db,
)

DETAIL = "AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."


@pytest_asyncio.fixture
async def user():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        row = User(
            username="timeout_user",
            nickname="Timeout User",
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
    with patch(
        "app.services.qna_service.QnAService.ask_question",
        AsyncMock(side_effect=httpx.ReadTimeout("timed out")),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as async_client:
            yield async_client


async def _sessions():
    async with SessionLocal() as db:
        return (await db.execute(select(ChatSession))).scalars().all()


async def _existing_session(user):
    async with SessionLocal() as db:
        row = ChatSession(user_id=user.id, title="lesson.pdf", document_id=DOC)
        db.add(row)
        await db.commit()
        return row.id


@pytest.mark.asyncio
async def test_first_question_timeout_returns_504_and_no_session(client):
    response = await client.post(f"/api/qna/{DOC}", json={"question": "질문"})

    assert response.status_code == 504, response.text
    assert response.json()["detail"] == DETAIL
    assert await _sessions() == []


@pytest.mark.asyncio
async def test_timeout_in_existing_session_keeps_session(client, user):
    session_id = await _existing_session(user)

    response = await client.post(f"/api/qna/{DOC}", json={"question": "질문"})

    assert response.status_code == 504, response.text
    assert response.json()["detail"] == DETAIL
    assert [s.id for s in await _sessions()] == [session_id]


@pytest.mark.asyncio
async def test_session_ask_timeout_returns_504(client, user):
    session_id = await _existing_session(user)

    response = await client.post(
        f"/api/qna/sessions/{session_id}/ask", json={"question": "질문"}
    )

    assert response.status_code == 504, response.text
    assert response.json()["detail"] == DETAIL
    assert [s.id for s in await _sessions()] == [session_id]


@pytest.mark.asyncio
async def test_first_question_error_hides_internal_detail(client):
    error = RuntimeError("fileSearchStores/user3store-abc/documents/x")
    with patch(
        "app.services.qna_service.QnAService.ask_question",
        AsyncMock(side_effect=error),
    ):
        response = await client.post(
            f"/api/qna/{DOC}", json={"question": "질문"}
        )

    assert response.status_code == 500, response.text
    assert "fileSearchStores" not in response.json()["detail"]
    assert await _sessions() == []
