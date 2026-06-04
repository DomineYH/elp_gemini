"""
Issue #5 보조: /auth/* 미들웨어 화이트리스트 회귀 테스트

WHITELIST_PREFIXES 에서 /auth/ 를 제거하고,
공개 auth 엔드포인트만 명시적으로 WHITELIST_PATHS 에 등록했으므로:
- 공개 경로(/auth/login, /auth/login/user, /auth/login/admin, /auth/logout)
  는 세션 없이 통과
- 보호 경로(/auth/me)는 세션 없으면 HTML → 302, JSON → 통과 후 401
- 알 수 없는 /auth/* 경로는 HTML → 302 리다이렉트
"""
from __future__ import annotations

import re
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models.users import User
from app.rate_limit import limiter

USER_PASSWORD = "test-password-1234"
_ADMIN_CSRF_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


async def _get_admin_csrf_token(client: AsyncClient) -> str:
    response = await client.get("/login/admin", follow_redirects=False)
    assert response.status_code == 200
    match = _ADMIN_CSRF_RE.search(response.text)
    assert match, "관리자 로그인 폼에 CSRF hidden input 이 있어야 함"
    return match.group(1)


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest_asyncio.fixture
async def normal_user(session_factory) -> User:
    from app.services.auth_service import AuthService

    async with session_factory() as session:
        hashed = AuthService.hash_password(USER_PASSWORD)
        user = User(
            username="testuser",
            nickname="testuser",
            hashed_password=hashed,
            is_admin=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def http_client(session_factory) -> AsyncIterator[AsyncClient]:
    async def _get_db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _reset_limiter_storage():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def disable_rate_limit():
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


# ------------------------------------------------------------------
# 1. 공개 auth 엔드포인트: 세션 없이도 미들웨어 통과
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unauthed_post_login_admin_passes(
    http_client, disable_rate_limit
):
    """POST /auth/login/admin 은 세션 없이도 미들웨어를 통과해야 함."""
    csrf_token = await _get_admin_csrf_token(http_client)
    resp = await http_client.post(
        "/auth/login/admin",
        data={
            "admin_id": "noone",
            "password": "wrong",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    # 미들웨어가 통과시켰고, 엔드포인트에서 401 반환
    assert resp.status_code == 401


# ------------------------------------------------------------------
# 2. /auth/me (HTML, 비인증) → 302 /login
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unauthed_html_get_auth_me_redirects(http_client):
    """GET /auth/me (HTML Accept) 에 세션이 없으면 302 /login."""
    resp = await http_client.get(
        "/auth/me",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


# ------------------------------------------------------------------
# 3. /auth/me (JSON, 비인증) → 미들웨어 통과 후 401
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unauthed_json_get_auth_me_unauthorized(http_client):
    """GET /auth/me (JSON Accept) 에 세션이 없으면 미들웨어를 통과하고
    엔드포인트에서 401 응답."""
    resp = await http_client.get(
        "/auth/me",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 401


# ------------------------------------------------------------------
# 4. 알 수 없는 /auth/* 경로 (HTML, 비인증) → 302 /login
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unauthed_html_unknown_auth_path_redirects(http_client):
    """GET /auth/foo (HTML Accept) 에 세션이 없으면 302 /login."""
    resp = await http_client.get(
        "/auth/foo",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


# ------------------------------------------------------------------
# 5. 세션 있는 사용자 /auth/me → 200
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_authed_user_accesses_auth_me(
    http_client, normal_user, disable_rate_limit
):
    """유효한 세션으로 GET /auth/me 시 200."""
    # /auth/login/user 는 사용자 지정 id + 비밀번호 기반 세션 설정 (issue #90)
    resp = await http_client.post(
        "/auth/login/user",
        data={
            "user_id": "testuser",
            "password": USER_PASSWORD,
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)

    # /auth/me 요청 (AsyncClient 가 세션 쿠키를 자동 보존)
    resp_me = await http_client.get(
        "/auth/me",
        headers={"Accept": "application/json"},
    )
    assert resp_me.status_code == 200
