"""
User-facing session history endpoint regression tests.

Covers issue #25 dashboard history contracts:
- authenticated users only see their own QnA sessions;
- cross-user history lookups return 404 to avoid session existence leaks;
- owners can read the full ordered message transcript.
"""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies import get_current_user
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.users import User
from app.routers import qna

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
TestingSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def override_get_db():
    """Test DB session override for the router-only ASGI app."""
    async with TestingSessionLocal() as database:
        yield database


@pytest_asyncio.fixture
async def db_tables():
    """Reset the shared test database for each history endpoint test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seeded_history(db_tables):
    """Create two users with separate sessions and deterministic messages."""
    base_time = datetime(2026, 5, 4, 9, 0, 0)

    async with TestingSessionLocal() as db:
        user_a = User(
            username="history_user_a",
            nickname="History User A",
            email="history-a@example.com",
            hashed_password="hashed-a",
            is_admin=False,
        )
        user_b = User(
            username="history_user_b",
            nickname="History User B",
            email="history-b@example.com",
            hashed_password="hashed-b",
            is_admin=False,
        )
        db.add_all([user_a, user_b])
        await db.flush()

        session_a_old = ChatSession(
            user_id=user_a.id,
            title="A old lesson",
            user_type="현직교사",
            created_at=base_time,
            updated_at=base_time + timedelta(minutes=10),
        )
        session_a_new = ChatSession(
            user_id=user_a.id,
            title="A new lesson",
            user_type="1학년",
            created_at=base_time + timedelta(hours=1),
            updated_at=base_time + timedelta(hours=1, minutes=20),
        )
        session_a_recent_message = ChatSession(
            user_id=user_a.id,
            title="A old row with recent message",
            user_type="3학년",
            created_at=base_time - timedelta(hours=1),
            updated_at=base_time + timedelta(minutes=5),
        )
        session_b = ChatSession(
            user_id=user_b.id,
            title="B private lesson",
            user_type="2학년",
            created_at=base_time + timedelta(hours=2),
            updated_at=base_time + timedelta(hours=2, minutes=5),
        )
        db.add_all([
            session_a_old,
            session_a_new,
            session_a_recent_message,
            session_b,
        ])
        await db.flush()

        db.add_all([
            ChatMessage(
                session_id=session_a_new.id,
                role=MessageRole.USER,
                content="첫 번째 질문",
                created_at=base_time + timedelta(hours=1, minutes=1),
            ),
            ChatMessage(
                session_id=session_a_new.id,
                role=MessageRole.ASSISTANT,
                content="첫 번째 답변",
                model_name="gemini-test",
                created_at=base_time + timedelta(hours=1, minutes=2),
            ),
            ChatMessage(
                session_id=session_a_new.id,
                role=MessageRole.USER,
                content="두 번째 질문",
                created_at=base_time + timedelta(hours=1, minutes=3),
            ),
            ChatMessage(
                session_id=session_b.id,
                role=MessageRole.USER,
                content="다른 사용자 질문",
                created_at=base_time + timedelta(hours=2, minutes=1),
            ),
            ChatMessage(
                session_id=session_a_recent_message.id,
                role=MessageRole.USER,
                content="가장 최근 활동 질문",
                created_at=base_time + timedelta(hours=3),
            ),
        ])
        await db.commit()

        return {
            "user_a": user_a,
            "user_b": user_b,
            "session_a_old": session_a_old,
            "session_a_new": session_a_new,
            "session_a_recent_message": session_a_recent_message,
            "session_b": session_b,
        }


@pytest_asyncio.fixture
async def client(seeded_history):
    """Build a router-only ASGI test app to avoid full app static startup."""
    active = {"user": seeded_history["user_a"]}

    async def override_current_user():
        return active["user"]

    test_app = FastAPI()
    test_app.include_router(qna.router)
    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_user] = override_current_user

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


def assert_pagination_metadata(payload, collection_key):
    """Lock count metadata to the returned page, not page cap semantics."""
    returned_count = len(payload[collection_key])
    assert payload["returned_count"] == returned_count
    assert payload["has_more"] is (
        payload["offset"] + returned_count < payload["total_count"]
    )


@pytest.mark.asyncio
async def test_list_my_sessions_only_returns_current_user_sessions(
    client,
    seeded_history,
):
    response = await client.get("/api/qna/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 3
    assert payload["returned_count"] == 3
    assert payload["limit"] == 50
    assert payload["offset"] == 0
    assert payload["has_more"] is False
    assert_pagination_metadata(payload, "sessions")

    sessions = payload["sessions"]
    returned_ids = {item["session_id"] for item in sessions}
    assert returned_ids == {
        seeded_history["session_a_old"].id,
        seeded_history["session_a_new"].id,
        seeded_history["session_a_recent_message"].id,
    }
    assert seeded_history["session_b"].id not in returned_ids
    assert sessions[0]["session_id"] == (
        seeded_history["session_a_recent_message"].id
    )

    for item in sessions:
        assert set(item) >= {
            "session_id",
            "title",
            "user_type",
            "created_at",
            "updated_at",
            "message_count",
            "last_message_at",
        }
        assert isinstance(item["message_count"], int)

    session_with_messages = next(
        item for item in sessions
        if item["session_id"] == seeded_history["session_a_new"].id
    )
    assert session_with_messages["title"] == "A new lesson"
    assert session_with_messages["user_type"] == "1학년"
    assert session_with_messages["message_count"] == 3
    assert session_with_messages["last_message_at"] is not None

    empty_session = next(
        item for item in sessions
        if item["session_id"] == seeded_history["session_a_old"].id
    )
    assert empty_session["message_count"] == 0
    assert empty_session["last_message_at"] is None


@pytest.mark.asyncio
async def test_list_my_sessions_supports_pagination(
    client,
    seeded_history,
):
    response = await client.get("/api/qna/sessions?limit=1&offset=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 3
    assert payload["returned_count"] == 1
    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert payload["has_more"] is True
    assert len(payload["sessions"]) == 1
    assert_pagination_metadata(payload, "sessions")


@pytest.mark.asyncio
async def test_list_my_sessions_last_page_has_no_more_results(
    client,
    seeded_history,
):
    response = await client.get("/api/qna/sessions?limit=2&offset=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 3
    assert payload["returned_count"] == 1
    assert payload["limit"] == 2
    assert payload["offset"] == 2
    assert payload["has_more"] is False
    assert len(payload["sessions"]) == 1
    assert_pagination_metadata(payload, "sessions")


@pytest.mark.asyncio
async def test_list_my_sessions_overrun_offset_keeps_total_count(
    client,
    seeded_history,
):
    response = await client.get("/api/qna/sessions?limit=10&offset=999")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 3
    assert payload["returned_count"] == 0
    assert payload["limit"] == 10
    assert payload["offset"] == 999
    assert payload["has_more"] is False
    assert payload["sessions"] == []
    assert_pagination_metadata(payload, "sessions")


@pytest.mark.asyncio
async def test_get_history_returns_404_for_another_users_session(
    client,
    seeded_history,
):
    response = await client.get(
        f"/api/qna/sessions/{seeded_history['session_b'].id}/history"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_history_owner_receives_ordered_messages(
    client,
    seeded_history,
):
    response = await client.get(
        f"/api/qna/sessions/{seeded_history['session_a_new'].id}/history"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == seeded_history["session_a_new"].id
    assert payload["total_count"] == 3
    assert payload["returned_count"] == 3
    assert payload["limit"] == 200
    assert payload["offset"] == 0
    assert payload["has_more"] is False
    assert_pagination_metadata(payload, "messages")

    messages = payload["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert [message["content"] for message in messages] == [
        "첫 번째 질문",
        "첫 번째 답변",
        "두 번째 질문",
    ]
    assert all("created_at" in message for message in messages)


@pytest.mark.asyncio
async def test_get_history_supports_pagination(
    client,
    seeded_history,
):
    first_page = await client.get(
        f"/api/qna/sessions/{seeded_history['session_a_new'].id}/history"
        "?limit=2&offset=0"
    )
    second_page = await client.get(
        f"/api/qna/sessions/{seeded_history['session_a_new'].id}/history"
        "?limit=2&offset=2"
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200

    first_payload = first_page.json()
    second_payload = second_page.json()

    assert first_payload["total_count"] == 3
    assert first_payload["returned_count"] == 2
    assert first_payload["limit"] == 2
    assert first_payload["offset"] == 0
    assert first_payload["has_more"] is True
    assert_pagination_metadata(first_payload, "messages")
    assert [message["content"] for message in first_payload["messages"]] == [
        "첫 번째 질문",
        "첫 번째 답변",
    ]

    assert second_payload["total_count"] == 3
    assert second_payload["returned_count"] == 1
    assert second_payload["limit"] == 2
    assert second_payload["offset"] == 2
    assert second_payload["has_more"] is False
    assert_pagination_metadata(second_payload, "messages")
    assert [message["content"] for message in second_payload["messages"]] == [
        "두 번째 질문",
    ]


@pytest.mark.asyncio
async def test_get_history_overrun_offset_keeps_total_count(
    client,
    seeded_history,
):
    response = await client.get(
        f"/api/qna/sessions/{seeded_history['session_a_new'].id}/history"
        "?limit=10&offset=999"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == seeded_history["session_a_new"].id
    assert payload["total_count"] == 3
    assert payload["returned_count"] == 0
    assert payload["limit"] == 10
    assert payload["offset"] == 999
    assert payload["has_more"] is False
    assert payload["messages"] == []
    assert_pagination_metadata(payload, "messages")
