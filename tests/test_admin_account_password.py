"""#264: 관리자 본인 비밀번호 변경과 환경변수 초기 관리자 시드."""

from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.db as db_mod
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models.users import User
from app.services.auth_service import AuthService
from tests.test_user_id_password_auth import (
    _build_session_cookie,
    _decode_session_cookie,
)

ADMIN_PASSWORD = "AdminPass123"
NEW_PASSWORD = "NewAdminPass456"
CSRF = "test-admin-csrf-token"
COOKIE = settings.SESSION_COOKIE_NAME
API = "/admin/api/account/password"


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
        for name, is_admin in (("admin", True), ("teacher1", False)):
            s.add(
                User(
                    username=name,
                    nickname=name,
                    hashed_password=AuthService.hash_password(ADMIN_PASSWORD),
                    is_admin=is_admin,
                )
            )
        await s.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def make_client(session_factory):
    async def _get_db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    clients: list[AsyncClient] = []
    with patch(
        "app.middleware.auth_middleware.async_session_maker",
        session_factory,
    ):

        def _make(cookie: str | None = None) -> AsyncClient:
            c = AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            )
            if cookie:
                c.cookies.set(COOKIE, cookie)
            clients.append(c)
            return c

        yield _make
        for c in clients:
            await c.aclose()
    app.dependency_overrides.pop(get_db, None)


async def _user(session_factory, username: str) -> User:
    async with session_factory() as s:
        return (
            await s.execute(select(User).where(User.username == username))
        ).scalar_one()


async def _cookie(session_factory, username: str = "admin") -> str:
    user = await _user(session_factory, username)
    return _build_session_cookie(
        {
            "user_id": user.id,
            "is_admin": user.is_admin,
            "username": user.username,
            "nickname": user.nickname,
            "session_version": user.session_version or 0,
            "admin_csrf_token": CSRF,
        }
    )


def _body(current=ADMIN_PASSWORD, new=NEW_PASSWORD, confirm=None) -> dict:
    return {
        "current_password": current,
        "new_password": new,
        "confirm_password": new if confirm is None else confirm,
    }


async def _post(client: AsyncClient, body: dict, csrf: bool = True):
    return await client.post(
        API, json=body, headers={"X-CSRF-Token": CSRF} if csrf else {}
    )


async def _assert_unchanged(session_factory):
    admin = await _user(session_factory, "admin")
    assert AuthService.verify_password(ADMIN_PASSWORD, admin.hashed_password)
    assert (admin.session_version or 0) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        _body(current="WrongPass999"),
        _body(new="short1"),
        _body(new="NoDigitsHere"),
        _body(confirm="Mismatch1234"),
    ],
    ids=["wrong-current", "too-short", "no-digit", "mismatch"],
)
async def test_rejected_change_returns_400(make_client, session_factory, body):
    client = make_client(await _cookie(session_factory))
    res = await _post(client, body)
    assert res.status_code == 400
    assert ADMIN_PASSWORD not in res.text
    await _assert_unchanged(session_factory)


@pytest.mark.asyncio
async def test_missing_csrf_returns_403(make_client, session_factory):
    client = make_client(await _cookie(session_factory))
    res = await _post(client, _body(), csrf=False)
    assert res.status_code == 403
    await _assert_unchanged(session_factory)


@pytest.mark.asyncio
async def test_regular_user_blocked(make_client, session_factory):
    cookie = await _cookie(session_factory, "teacher1")
    res = await _post(make_client(cookie), _body())
    assert res.status_code == 403
    page = await make_client(cookie).get(
        "/admin/account",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert page.status_code in (302, 303, 403)
    await _assert_unchanged(session_factory)


@pytest.mark.asyncio
async def test_account_page_renders_for_admin(make_client, session_factory):
    res = await make_client(await _cookie(session_factory)).get(
        "/admin/account", headers={"Accept": "text/html"}
    )
    assert res.status_code == 200
    assert 'name="csrf-token"' in res.text
    assert API in res.text
    assert 'href="/admin/account"' in res.text


@pytest.mark.asyncio
async def test_success_rotates_other_sessions_keeps_caller(
    make_client, session_factory
):
    old_cookie = await _cookie(session_factory)
    other = make_client(old_cookie)
    caller = make_client(old_cookie)

    res = await _post(caller, _body())
    assert res.status_code == 200
    assert NEW_PASSWORD not in res.text

    admin = await _user(session_factory, "admin")
    assert not AuthService.verify_password(
        ADMIN_PASSWORD, admin.hashed_password
    )
    assert AuthService.verify_password(NEW_PASSWORD, admin.hashed_password)
    assert admin.session_version == 1

    assert (await other.get("/auth/me")).status_code == 401
    assert (await caller.get("/auth/me")).status_code == 200
    # 이 요청이 만든 버전(0+1)을 세션에 저장한다
    assert _decode_session_cookie(res.cookies[COOKIE])["session_version"] == 1


@pytest.mark.asyncio
async def test_stale_request_cannot_override_concurrent_change(
    session_factory,
):
    """A가 인증을 통과한 뒤 B가 먼저 바꾸면 A의 변경은 거부된다."""
    b_hash = AuthService.hash_password("ByOtherReq789")
    async with session_factory() as a_db:
        stale_admin = (
            await a_db.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        async with session_factory() as b_db:
            admin = (
                await b_db.execute(select(User).where(User.username == "admin"))
            ).scalar_one()
            admin.hashed_password = b_hash
            admin.session_version = 1
            await b_db.commit()

        with pytest.raises(ValueError):
            await AuthService(a_db).change_own_password(
                stale_admin, ADMIN_PASSWORD, NEW_PASSWORD
            )

    admin = await _user(session_factory, "admin")
    assert admin.hashed_password == b_hash
    assert admin.session_version == 1


# ===== 초기 관리자 시드 =====


@pytest_asyncio.fixture
async def seed_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(db_mod, "async_session_maker", factory)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _admin_row(factory) -> User | None:
    async with factory() as s:
        return (
            await s.execute(select(User).where(User.username == "admin"))
        ).scalar_one_or_none()


def _env(monkeypatch, *, debug: bool, password: str | None):
    monkeypatch.setattr(settings, "DEBUG", debug)
    monkeypatch.setattr(settings, "ADMIN_INITIAL_PASSWORD", password)


@pytest.mark.asyncio
async def test_seed_skipped_in_production_without_env(
    seed_db, monkeypatch, caplog
):
    _env(monkeypatch, debug=False, password=None)
    await db_mod.seed_initial_admin()
    assert await _admin_row(seed_db) is None
    assert "ADMIN_INITIAL_PASSWORD" in caplog.text


@pytest.mark.asyncio
async def test_seed_uses_env_password(seed_db, monkeypatch):
    _env(monkeypatch, debug=False, password="EnvAdmin2026")
    await db_mod.seed_initial_admin()
    admin = await _admin_row(seed_db)
    assert admin.is_admin
    assert AuthService.verify_password("EnvAdmin2026", admin.hashed_password)


@pytest.mark.asyncio
async def test_seed_debug_default_without_env(seed_db, monkeypatch):
    _env(monkeypatch, debug=True, password=None)
    await db_mod.seed_initial_admin()
    admin = await _admin_row(seed_db)
    assert AuthService.verify_password("admin1234", admin.hashed_password)


@pytest.mark.asyncio
async def test_seed_never_overwrites_existing_admin(seed_db, monkeypatch):
    _env(monkeypatch, debug=False, password="EnvAdmin2026")
    await db_mod.seed_initial_admin()
    monkeypatch.setattr(settings, "ADMIN_INITIAL_PASSWORD", "Another2027")
    await db_mod.seed_initial_admin()
    admin = await _admin_row(seed_db)
    assert AuthService.verify_password("EnvAdmin2026", admin.hashed_password)


@pytest.mark.asyncio
async def test_weak_env_password_fails_fast_without_echo(seed_db, monkeypatch):
    _env(monkeypatch, debug=False, password="weakpass")
    with pytest.raises(RuntimeError) as exc:
        await db_mod.seed_initial_admin()
    assert "ADMIN_INITIAL_PASSWORD" in str(exc.value)
    assert "weakpass" not in str(exc.value)
    assert await _admin_row(seed_db) is None
