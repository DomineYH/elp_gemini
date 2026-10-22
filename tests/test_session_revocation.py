"""
로그아웃·비밀번호 변경 후 이전 세션 쿠키 무효화 (#169)

서명 쿠키 세션은 서버 측 상태가 없으므로 users.session_version을
세션에 저장하고 요청마다 비교한다.
"""

from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models.users import User
from app.rate_limit import limiter
from app.services.auth_service import AuthService

USER_ID = "teach169"
USER_PASSWORD = "TeacherPass123"
NEW_PASSWORD = "ChangedPass123"
COOKIE = settings.SESSION_COOKIE_NAME


@pytest_asyncio.fixture
async def session_factory():
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
    async with factory() as s:
        s.add(
            User(
                username=USER_ID,
                nickname=USER_ID,
                hashed_password=AuthService.hash_password(USER_PASSWORD),
                is_admin=False,
            )
        )
        await s.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def store_delete():
    """로그아웃의 File Search 스토어 삭제가 실제 API로 나가지 않게 한다."""
    with patch("app.services.file_search_service.FileSearchService") as fss:
        fss.return_value.delete_store_by_display_name = AsyncMock()
        yield fss.return_value.delete_store_by_display_name


@pytest_asyncio.fixture
async def make_client(session_factory, store_delete):
    async def _get_db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    clients: list[AsyncClient] = []
    # HTML 경로의 미들웨어 DB 검증도 같은 테스트 DB를 보게 한다
    with patch(
        "app.middleware.auth_middleware.async_session_maker",
        session_factory,
    ):

        def _make() -> AsyncClient:
            c = AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            )
            clients.append(c)
            return c

        yield _make
        for c in clients:
            await c.aclose()
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _no_rate_limit():
    original = limiter.enabled
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = original


async def _login(client: AsyncClient, password: str = USER_PASSWORD) -> str:
    res = await client.post(
        "/auth/login/user",
        data={"user_id": USER_ID, "password": password},
        follow_redirects=False,
    )
    assert res.status_code in (200, 302)
    cookie = client.cookies.get(COOKIE)
    assert cookie
    return cookie


async def _logout(make_client, cookie: str) -> int:
    # 세션 쿠키는 Secure 속성이라 http 테스트 클라이언트가 자동 전송하지 않음
    c = make_client()
    c.cookies.set(COOKIE, cookie)
    res = await c.post("/auth/logout", follow_redirects=False)
    return res.status_code


async def _me_status(make_client, cookie: str) -> int:
    c = make_client()
    c.cookies.set(COOKIE, cookie)
    res = await c.get("/auth/me", headers={"Accept": "application/json"})
    return res.status_code


@pytest.mark.asyncio
async def test_old_cookie_rejected_after_logout(make_client, store_delete):
    client = make_client()
    old_cookie = await _login(client)
    assert await _me_status(make_client, old_cookie) == 200

    assert await _logout(make_client, old_cookie) == 302

    assert await _me_status(make_client, old_cookie) == 401
    store_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_cookie_html_redirects_to_login_after_logout(make_client):
    client = make_client()
    old_cookie = await _login(client)
    await _logout(make_client, old_cookie)

    c = make_client()
    c.cookies.set(COOKIE, old_cookie)
    res = await c.get(
        "/dashboard",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert res.headers["location"].startswith("/login")


@pytest.mark.asyncio
async def test_relogin_after_logout_works(make_client):
    old_cookie = await _login(make_client())
    await _logout(make_client, old_cookie)

    new_cookie = await _login(make_client())
    assert await _me_status(make_client, new_cookie) == 200


@pytest.mark.asyncio
async def test_logout_with_revoked_cookie_does_not_kill_new_session(
    make_client,
):
    """이미 폐기된 쿠키로 로그아웃해도 새 세션은 유지된다."""
    stale_cookie = await _login(make_client())
    await _logout(make_client, stale_cookie)

    new_cookie = await _login(make_client())
    await _logout(make_client, stale_cookie)

    assert await _me_status(make_client, new_cookie) == 200


@pytest.mark.asyncio
async def test_old_cookie_rejected_after_admin_password_change(
    make_client, session_factory
):
    old_cookie = await _login(make_client())
    assert await _me_status(make_client, old_cookie) == 200

    async with session_factory() as s:
        user_pk = (
            await s.execute(select(User.id).where(User.username == USER_ID))
        ).scalar_one()
        await AuthService(s).admin_set_user_password(user_pk, NEW_PASSWORD)

    assert await _me_status(make_client, old_cookie) == 401
    new_cookie = await _login(make_client(), NEW_PASSWORD)
    assert await _me_status(make_client, new_cookie) == 200


async def _user_pk(session_factory) -> int:
    async with session_factory() as s:
        return (
            await s.execute(select(User.id).where(User.username == USER_ID))
        ).scalar_one()


async def _db_version(session_factory, user_pk: int) -> int:
    async with session_factory() as s:
        return (
            await s.execute(
                select(User.session_version).where(User.id == user_pk)
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_concurrent_password_changes_each_bump_version(session_factory):
    """두 세션이 같은 버전을 읽은 뒤 변경해도 버전은 두 번 오른다."""
    user_pk = await _user_pk(session_factory)
    async with session_factory() as a, session_factory() as b:
        # 참조를 잡아 두어야 identity map에 읽은 값이 남는다
        _held = [await a.get(User, user_pk), await b.get(User, user_pk)]

        await AuthService(a).admin_set_user_password(user_pk, NEW_PASSWORD)
        cookie_version = await _db_version(session_factory, user_pk)
        await AuthService(b).admin_set_user_password(user_pk, USER_PASSWORD)

    assert await _db_version(session_factory, user_pk) == 2
    async with session_factory() as s:
        user = await s.get(User, user_pk)
        assert not AuthService.session_version_matches(user, cookie_version)


@pytest.mark.asyncio
async def test_stale_logout_does_not_roll_back_version(session_factory):
    """지연된 로그아웃이 더 최신 버전을 덮어쓰지 않는다."""
    user_pk = await _user_pk(session_factory)
    async with session_factory() as a, session_factory() as b:
        # 참조를 잡아 두어야 identity map에 읽은 값이 남는다
        _held = await a.get(User, user_pk)

        await AuthService(b).admin_set_user_password(user_pk, NEW_PASSWORD)
        await AuthService(b).admin_set_user_password(user_pk, USER_PASSWORD)

        assert await AuthService(a).revoke_sessions_if_current(user_pk, 0) is (
            False
        )

    assert await _db_version(session_factory, user_pk) == 2


@pytest.mark.asyncio
async def test_old_cookie_rejected_after_user_delete(
    make_client, session_factory
):
    old_cookie = await _login(make_client())

    async with session_factory() as s:
        await s.execute(delete(User).where(User.username == USER_ID))
        await s.commit()

    assert await _me_status(make_client, old_cookie) == 401


@pytest.mark.asyncio
async def test_session_version_migration_adds_column(tmp_path):
    from sqlalchemy import inspect, text

    from app.migrations import ensure_users_session_version_column

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/m.db")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO users (id) VALUES (1)"))

    assert await ensure_users_session_version_column(engine) is True
    assert await ensure_users_session_version_column(engine) is False

    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {x["name"] for x in inspect(c).get_columns("users")}
        )
        value = (
            await conn.execute(text("SELECT session_version FROM users"))
        ).scalar_one()
    assert "session_version" in cols
    assert value == 0
    await engine.dispose()
