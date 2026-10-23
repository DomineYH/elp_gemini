"""관리자 QnA 로그 API가 세션 작성자 user_id/username을 내려준다 (#268)."""

from typing import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies import get_current_admin
from app.main import app
from app.models.chat_sessions import ChatSession
from app.models.users import User


@pytest_asyncio.fixture
async def http_client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        user = User(username="teacher7", nickname="T")
        session.add(user)
        await session.flush()
        session.add(ChatSession(user_id=user.id, title="질문"))
        await session.commit()

    async def _get_db_override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_admin] = lambda: User(
        id=99, username="admin", nickname="Admin", is_admin=True
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides = {}
        await engine.dispose()


async def test_qna_logs_include_username(http_client):
    resp = await http_client.get("/admin/api/qna-logs")

    assert resp.status_code == 200
    session = resp.json()["sessions"][0]
    assert session["username"] == "teacher7"
    assert isinstance(session["user_id"], int)


def test_session_card_shows_escaped_username():
    from pathlib import Path

    source = Path("app/templates/admin/admin_qna_logs.html").read_text(
        encoding="utf-8"
    )
    assert "${escapeHtml(session.username || '-')}" in source
