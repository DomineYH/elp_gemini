"""
#452: 공개 가입(POST /auth/register)의 IP당 요청 제한.

입력 검증을 통과한 요청만 세고, 한도를 넘으면 가입 폼을 안내 문구와
입력한 아이디로 429 다시 그린다. 로그인 한도와 횟수는 따로다.
"""

from __future__ import annotations

import base64
import json
from typing import AsyncIterator

import itsdangerous
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from limits import parse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.rate_limit as rate_limit
from app.config import Settings, settings
from app.db import Base, get_db
from app.main import app
from app.models.users import User
from app.rate_limit import limiter
from app.services.auth_service import AuthService

PASSWORD = "TeacherPass123"
LIMIT_MESSAGE = "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."
DUPLICATE_MESSAGE = "이미 사용 중인 아이디입니다."
OTHER_IP = "198.51.100.7"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _enable_register_limit(monkeypatch):
    """두 스위치를 명시적으로 켜고 가입 한도를 3/minute 로 낮춘다."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(
        rate_limit, "_register_ip_limit_item", parse("3/minute")
    )
    limiter.reset()
    yield
    limiter.reset()


@pytest_asyncio.fixture
async def make_client(session_factory):
    async def _get_db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    clients: list[AsyncClient] = []

    def _make(ip: str = "127.0.0.1") -> AsyncClient:
        transport = ASGITransport(app=app, client=(ip, 50000))
        c = AsyncClient(transport=transport, base_url="http://test")
        clients.append(c)
        return c

    try:
        yield _make
    finally:
        for c in clients:
            await c.aclose()
        app.dependency_overrides.pop(get_db, None)


async def _register(
    client: AsyncClient,
    user_id: str,
    password: str = PASSWORD,
    password_confirm: str | None = None,
):
    # 성공 가입은 세션 쿠키를 주므로 매번 비로그인 상태로 보낸다
    client.cookies.clear()
    return await client.post(
        "/auth/register",
        data={
            "user_id": user_id,
            "password": password,
            "password_confirm": (
                password if password_confirm is None else password_confirm
            ),
        },
        follow_redirects=False,
    )


async def _user_count(session_factory) -> int:
    async with session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(User))
        ).scalar_one()


async def _usernames(session_factory) -> set[str]:
    async with session_factory() as session:
        rows = await session.execute(select(User.username))
        return set(rows.scalars().all())


def _session_data(response) -> dict:
    cookie = response.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie is None:
        return {}
    signer = itsdangerous.TimestampSigner(str(settings.SECRET_KEY))
    payload = signer.unsign(cookie, max_age=settings.SESSION_MAX_AGE)
    return json.loads(base64.b64decode(payload))


def test_register_limit_default():
    assert Settings.model_fields["REGISTER_RATE_LIMIT"].default == "30/minute"


@pytest.mark.asyncio
async def test_fourth_valid_registration_returns_form(
    make_client, session_factory
):
    client = make_client()
    for user_id in ("teach1", "teach2", "teach3"):
        response = await _register(client, user_id)
        assert response.status_code == 302, user_id

    response = await _register(client, "TeachFour")
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("text/html")
    assert 'action="/auth/register"' in response.text
    assert LIMIT_MESSAGE in response.text
    assert 'value="TeachFour"' in response.text
    assert await _user_count(session_factory) == 3
    assert "teachfour" not in await _usernames(session_factory)
    assert "user_id" not in _session_data(response)

    # 같은 IP 의 가입 화면과 로그인은 가입 한도와 따로 센다
    client.cookies.clear()
    page = await client.get("/register", follow_redirects=False)
    assert page.status_code == 200
    login = await client.post(
        "/auth/login/user",
        data={"user_id": "teach1", "password": PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 302

    # 다른 IP 의 가입은 막히지 않는다
    other = await _register(make_client(OTHER_IP), "other1")
    assert other.status_code == 302


@pytest.mark.asyncio
async def test_invalid_forms_do_not_consume_quota(make_client):
    client = make_client()
    invalid = [
        ("bad1", PASSWORD, "Different123"),
        ("bad2", PASSWORD, "Mismatch999"),
        ("bad_id!", PASSWORD, PASSWORD),
        ("toolongid10", PASSWORD, PASSWORD),
        ("weak1", "short", "short"),
    ]
    for user_id, password, confirm in invalid:
        response = await _register(client, user_id, password, confirm)
        assert response.status_code == 400, user_id

    response = await _register(client, "valid1")
    assert response.status_code == 302


@pytest.mark.asyncio
async def test_duplicate_ids_consume_quota(make_client, session_factory):
    async with session_factory() as session:
        session.add(
            User(
                username="taken1",
                nickname="taken1",
                hashed_password=AuthService.hash_password(PASSWORD),
                is_admin=False,
            )
        )
        await session.commit()

    client = make_client()
    for _ in range(3):
        response = await _register(client, "taken1")
        assert response.status_code == 409
        assert DUPLICATE_MESSAGE in response.text

    response = await _register(client, "fresh1")
    assert response.status_code == 429
    assert await _user_count(session_factory) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting_enabled", "limiter_enabled"),
    [(False, True), (True, False)],
)
async def test_disabled_register_limit(
    make_client, monkeypatch, setting_enabled, limiter_enabled
):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", setting_enabled)
    monkeypatch.setattr(limiter, "enabled", limiter_enabled)
    client = make_client()
    for n in range(10):
        response = await _register(client, f"user{n}")
        assert response.status_code == 302, n
