"""
Issue #10: 일반 사용자 이메일+비밀번호 로그인/등록 전환 회귀 테스트.

Lane E locks the expected product behavior while the implementation lanes add
models, services, routes, and templates. These tests intentionally exercise the
public HTTP flow plus DB state so missing lanes fail with clear evidence.
"""
from __future__ import annotations

import base64
import importlib
import json
from typing import AsyncIterator
from urllib.parse import parse_qs, urlparse

import itsdangerous
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

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models.users import User
from app.rate_limit import limiter
from app.services.auth_service import AuthService

TEACHER_EMAIL = "teacher@example.com"
TEACHER_PASSWORD = "TeacherPass123"
PRESERVICE_EMAIL = "preservice@example.com"
PRESERVICE_PASSWORD = "PreservicePass123"
ADMIN_PASSWORD = "AdminPass123"
NEW_USER_PASSWORD = "NewUserPass123"
NEW_ADMIN_SET_PASSWORD = "ChangedPass123"
ADMIN_CSRF_TOKEN = "test-admin-csrf-token"


def _optional_user_profile_model():
    """Import UserProfile when its lane is present; ignore only absence."""
    try:
        module = importlib.import_module("app.models.user_profiles")
    except ModuleNotFoundError as exc:
        if exc.name == "app.models.user_profiles":
            return None
        raise
    return getattr(module, "UserProfile", None)


def _require_user_profile_model():
    model = _optional_user_profile_model()
    if model is None:
        pytest.fail(
            "Expected Lane A to provide app.models.user_profiles.UserProfile"
        )
    return model


@pytest_asyncio.fixture
async def session_factory():
    """Per-test in-memory DB, including optional Lane A metadata."""
    _optional_user_profile_model()
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
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncIterator[AsyncClient]:
    async def _get_db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as async_client:
        yield async_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    """User-auth tests are not rate-limit tests; keep them deterministic."""
    original_enabled = limiter.enabled
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = original_enabled


def _build_session_cookie(data: dict) -> str:
    signer = itsdangerous.TimestampSigner(str(settings.SECRET_KEY))
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


def _decode_session_cookie(cookie: str) -> dict:
    signer = itsdangerous.TimestampSigner(str(settings.SECRET_KEY))
    payload = signer.unsign(cookie, max_age=settings.SESSION_MAX_AGE)
    return json.loads(base64.b64decode(payload))


async def _create_user(
    session_factory,
    *,
    username: str,
    email: str | None,
    password: str,
    is_admin: bool = False,
) -> User:
    async with session_factory() as session:
        user = User(
            username=username,
            nickname=username,
            email=email,
            hashed_password=AuthService.hash_password(password),
            is_admin=is_admin,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _create_regular_user_with_profile(
    session_factory,
    *,
    username: str,
    email: str,
    password: str,
) -> User:
    async with session_factory() as session:
        user = User(
            username=username,
            nickname="teacher",
            email=email,
            hashed_password=AuthService.hash_password(password),
            is_admin=False,
        )
        session.add(user)
        await session.flush()

        profile_model = _optional_user_profile_model()
        if profile_model is not None:
            session.add(
                profile_model(
                    user_id=user.id,
                    role="teacher",
                    teacher_region="서울",
                    teacher_career_years=5,
                )
            )
        await session.commit()
        await session.refresh(user)
        return user


async def _fetch_user_by_email(session_factory, email: str) -> User | None:
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()


async def _fetch_user_by_username(
    session_factory, username: str
) -> User | None:
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()


async def _assert_profile(
    session_factory,
    *,
    user: User,
    role: str,
    expected: dict,
) -> None:
    profile_model = _require_user_profile_model()
    async with session_factory() as session:
        result = await session.execute(
            select(profile_model).where(profile_model.user_id == user.id)
        )
        profile = result.scalar_one_or_none()

    assert profile is not None
    assert profile.role == role
    for attr, value in expected.items():
        assert getattr(profile, attr) == value


async def _register_teacher(
    client: AsyncClient,
    *,
    email: str = TEACHER_EMAIL,
    password: str = TEACHER_PASSWORD,
):
    return await client.post(
        "/auth/register",
        data={
            "email": email,
            "password": password,
            "role": "teacher",
            "teacher_region": "서울",
            "teacher_career_years": "5",
        },
        follow_redirects=False,
    )


async def _register_preservice(
    client: AsyncClient,
    *,
    email: str = PRESERVICE_EMAIL,
    password: str = PRESERVICE_PASSWORD,
):
    return await client.post(
        "/auth/register",
        data={
            "email": email,
            "password": password,
            "role": "preservice_teacher",
            "preservice_university_region": "서울교대",
            "preservice_grade": "3",
        },
        follow_redirects=False,
    )


def _assert_form_error(response):
    assert response.status_code in {200, 400, 422}
    if response.status_code == 200:
        lowered = response.text.lower()
        assert "error" in lowered or "오류" in response.text


@pytest.mark.asyncio
async def test_login_page_uses_email_password_without_invite_code(client):
    response = await client.get("/login", follow_redirects=False)

    assert response.status_code == 200
    body = response.text
    assert 'action="/auth/login/user"' in body
    assert 'type="email"' in body
    assert 'name="email"' in body
    assert 'type="password"' in body
    assert 'name="password"' in body
    assert 'name="invite_code"' not in body
    assert 'id="invite_code"' not in body
    assert "초대 코드" not in body


@pytest.mark.asyncio
async def test_legacy_username_login_no_longer_creates_session(
    client,
    session_factory,
):
    response = await client.post(
        "/auth/login",
        data={"username": "legacy_user", "nickname": "Legacy"},
        follow_redirects=False,
    )

    assert response.status_code == 410
    assert settings.SESSION_COOKIE_NAME not in response.cookies
    assert await _fetch_user_by_username(session_factory, "legacy_user") is None


@pytest.mark.asyncio
async def test_unregistered_email_login_routes_to_registration(client):
    response = await client.post(
        "/auth/login/user",
        data={"email": " New.Teacher@Example.COM ", "password": "AnyPass123"},
        follow_redirects=False,
    )

    assert response.status_code in {200, 302, 303}
    if response.status_code in {302, 303}:
        location = response.headers["location"]
        parsed = urlparse(location)
        assert parsed.path == "/register"
        assert parse_qs(parsed.query)["email"] == ["new.teacher@example.com"]
        return

    body = response.text.lower()
    assert 'action="/auth/register"' in body
    assert "new.teacher@example.com" in body


@pytest.mark.asyncio
async def test_teacher_registration_creates_hashed_user_and_profile(
    client, session_factory
):
    response = await _register_teacher(client)

    assert response.status_code in {302, 303}
    assert response.headers["location"] in {"/", "/dashboard"}

    user = await _fetch_user_by_email(session_factory, TEACHER_EMAIL)
    assert user is not None
    assert user.hashed_password != TEACHER_PASSWORD
    assert AuthService.verify_password(
        TEACHER_PASSWORD, user.hashed_password
    )
    assert not user.is_admin
    await _assert_profile(
        session_factory,
        user=user,
        role="teacher",
        expected={
            "teacher_region": "서울",
            "teacher_career_years": 5,
            "preservice_university_region": None,
            "preservice_grade": None,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"teacher_region": "화성"},
        {"teacher_career_years": "-1"},
        {"teacher_career_years": "five"},
    ],
)
async def test_teacher_registration_rejects_invalid_region_or_career(
    client, session_factory, override
):
    payload = {
        "email": "invalid-teacher@example.com",
        "password": TEACHER_PASSWORD,
        "role": "teacher",
        "teacher_region": "서울",
        "teacher_career_years": "5",
    }
    payload.update(override)

    response = await client.post(
        "/auth/register", data=payload, follow_redirects=False
    )

    _assert_form_error(response)
    user = await _fetch_user_by_email(
        session_factory, "invalid-teacher@example.com"
    )
    assert user is None


@pytest.mark.asyncio
async def test_preservice_registration_creates_profile(
    client, session_factory
):
    response = await _register_preservice(client)

    assert response.status_code in {302, 303}
    assert response.headers["location"] in {"/", "/dashboard"}

    user = await _fetch_user_by_email(session_factory, PRESERVICE_EMAIL)
    assert user is not None
    assert user.hashed_password != PRESERVICE_PASSWORD
    assert AuthService.verify_password(
        PRESERVICE_PASSWORD, user.hashed_password
    )
    await _assert_profile(
        session_factory,
        user=user,
        role="preservice_teacher",
        expected={
            "teacher_region": None,
            "teacher_career_years": None,
            "preservice_university_region": "서울교대",
            "preservice_grade": 3,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"preservice_university_region": "하버드"},
        {"preservice_grade": "0"},
        {"preservice_grade": "5"},
    ],
)
async def test_preservice_registration_rejects_invalid_region_or_grade(
    client, session_factory, override
):
    payload = {
        "email": "invalid-preservice@example.com",
        "password": PRESERVICE_PASSWORD,
        "role": "preservice_teacher",
        "preservice_university_region": "서울교대",
        "preservice_grade": "3",
    }
    payload.update(override)

    response = await client.post(
        "/auth/register", data=payload, follow_redirects=False
    )

    _assert_form_error(response)
    user = await _fetch_user_by_email(
        session_factory, "invalid-preservice@example.com"
    )
    assert user is None


@pytest.mark.asyncio
async def test_existing_email_password_login_sets_session(
    client, session_factory
):
    user = await _create_regular_user_with_profile(
        session_factory,
        username="existing_teacher",
        email=TEACHER_EMAIL,
        password=TEACHER_PASSWORD,
    )

    response = await client.post(
        "/auth/login/user",
        data={"email": TEACHER_EMAIL.upper(), "password": TEACHER_PASSWORD},
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["location"] in {"/", "/dashboard"}
    session_cookie = response.cookies.get(settings.SESSION_COOKIE_NAME)
    assert session_cookie is not None
    session = _decode_session_cookie(session_cookie)
    assert session["user_id"] == user.id
    assert session["is_admin"] is False


@pytest.mark.asyncio
async def test_existing_email_wrong_password_does_not_create_session(
    client, session_factory
):
    await _create_regular_user_with_profile(
        session_factory,
        username="wrong_password_teacher",
        email=TEACHER_EMAIL,
        password=TEACHER_PASSWORD,
    )

    response = await client.post(
        "/auth/login/user",
        data={"email": TEACHER_EMAIL, "password": "WrongPass123"},
        follow_redirects=False,
    )

    assert response.status_code in {400, 401}
    assert settings.SESSION_COOKIE_NAME not in response.cookies


@pytest.mark.asyncio
async def test_admin_can_change_regular_user_password(
    client, session_factory
):
    admin = await _create_user(
        session_factory,
        username="admin-password-manager",
        email="admin@example.com",
        password=ADMIN_PASSWORD,
        is_admin=True,
    )
    regular = await _create_regular_user_with_profile(
        session_factory,
        username="managed_teacher",
        email="managed@example.com",
        password=TEACHER_PASSWORD,
    )
    admin_cookie = _build_session_cookie(
        {
            "user_id": admin.id,
            "is_admin": True,
            "username": admin.username,
            "nickname": admin.nickname,
            "admin_csrf_token": ADMIN_CSRF_TOKEN,
        }
    )

    response = await client.post(
        f"/admin/api/users/{regular.id}/password",
        json={"new_password": NEW_ADMIN_SET_PASSWORD},
        cookies={settings.SESSION_COOKIE_NAME: admin_cookie},
        headers={"X-CSRF-Token": ADMIN_CSRF_TOKEN},
        follow_redirects=False,
    )

    assert response.status_code in {200, 204}
    changed = await _fetch_user_by_email(session_factory, "managed@example.com")
    assert changed is not None
    assert AuthService.verify_password(
        NEW_ADMIN_SET_PASSWORD, changed.hashed_password
    )
    assert not AuthService.verify_password(
        TEACHER_PASSWORD, changed.hashed_password
    )

    old_login = await client.post(
        "/auth/login/user",
        data={"email": "managed@example.com", "password": TEACHER_PASSWORD},
        follow_redirects=False,
    )
    assert old_login.status_code in {400, 401}

    new_login = await client.post(
        "/auth/login/user",
        data={
            "email": "managed@example.com",
            "password": NEW_ADMIN_SET_PASSWORD,
        },
        follow_redirects=False,
    )
    assert new_login.status_code in {302, 303}


@pytest.mark.asyncio
async def test_admin_password_change_requires_csrf_token(
    client,
    session_factory,
):
    admin = await _create_user(
        session_factory,
        username="admin-password-csrf",
        email="admin-csrf@example.com",
        password=ADMIN_PASSWORD,
        is_admin=True,
    )
    regular = await _create_regular_user_with_profile(
        session_factory,
        username="csrf_target",
        email="csrf-target@example.com",
        password=TEACHER_PASSWORD,
    )
    admin_cookie = _build_session_cookie(
        {
            "user_id": admin.id,
            "is_admin": True,
            "username": admin.username,
            "nickname": admin.nickname,
            "admin_csrf_token": ADMIN_CSRF_TOKEN,
        }
    )

    response = await client.post(
        f"/admin/api/users/{regular.id}/password",
        json={"new_password": NEW_ADMIN_SET_PASSWORD},
        cookies={settings.SESSION_COOKIE_NAME: admin_cookie},
        follow_redirects=False,
    )

    assert response.status_code == 403
    unchanged = await _fetch_user_by_email(
        session_factory, "csrf-target@example.com"
    )
    assert unchanged is not None
    assert AuthService.verify_password(
        TEACHER_PASSWORD, unchanged.hashed_password
    )


@pytest.mark.asyncio
async def test_admin_password_change_uses_shared_password_policy(
    client,
    session_factory,
):
    admin = await _create_user(
        session_factory,
        username="admin-password-policy",
        email="admin-policy@example.com",
        password=ADMIN_PASSWORD,
        is_admin=True,
    )
    regular = await _create_regular_user_with_profile(
        session_factory,
        username="weak_policy_target",
        email="weak-policy@example.com",
        password=TEACHER_PASSWORD,
    )
    admin_cookie = _build_session_cookie(
        {
            "user_id": admin.id,
            "is_admin": True,
            "username": admin.username,
            "nickname": admin.nickname,
            "admin_csrf_token": ADMIN_CSRF_TOKEN,
        }
    )

    response = await client.post(
        f"/admin/api/users/{regular.id}/password",
        json={"new_password": "NoDigitsHere"},
        cookies={settings.SESSION_COOKIE_NAME: admin_cookie},
        headers={"X-CSRF-Token": ADMIN_CSRF_TOKEN},
        follow_redirects=False,
    )

    assert response.status_code == 400
    unchanged = await _fetch_user_by_email(
        session_factory, "weak-policy@example.com"
    )
    assert unchanged is not None
    assert AuthService.verify_password(
        TEACHER_PASSWORD, unchanged.hashed_password
    )


@pytest.mark.asyncio
async def test_admin_password_change_rejects_legacy_emailless_user(
    client,
    session_factory,
):
    admin = await _create_user(
        session_factory,
        username="admin-password-legacy",
        email="admin-legacy@example.com",
        password=ADMIN_PASSWORD,
        is_admin=True,
    )
    legacy = await _create_user(
        session_factory,
        username="legacy-invite-code",
        email=None,
        password=TEACHER_PASSWORD,
        is_admin=False,
    )
    admin_cookie = _build_session_cookie(
        {
            "user_id": admin.id,
            "is_admin": True,
            "username": admin.username,
            "nickname": admin.nickname,
            "admin_csrf_token": ADMIN_CSRF_TOKEN,
        }
    )

    response = await client.post(
        f"/admin/api/users/{legacy.id}/password",
        json={"new_password": NEW_ADMIN_SET_PASSWORD},
        cookies={settings.SESSION_COOKIE_NAME: admin_cookie},
        headers={"X-CSRF-Token": ADMIN_CSRF_TOKEN},
        follow_redirects=False,
    )

    assert response.status_code == 400
    unchanged = await _fetch_user_by_username(
        session_factory, "legacy-invite-code"
    )
    assert unchanged is not None
    assert AuthService.verify_password(
        TEACHER_PASSWORD, unchanged.hashed_password
    )


@pytest.mark.asyncio
async def test_non_admin_cannot_change_user_password(client, session_factory):
    actor = await _create_regular_user_with_profile(
        session_factory,
        username="non_admin_actor",
        email="actor@example.com",
        password=NEW_USER_PASSWORD,
    )
    target = await _create_regular_user_with_profile(
        session_factory,
        username="target_teacher",
        email="target@example.com",
        password=TEACHER_PASSWORD,
    )
    actor_cookie = _build_session_cookie(
        {
            "user_id": actor.id,
            "is_admin": False,
            "username": actor.username,
            "nickname": actor.nickname,
        }
    )

    response = await client.post(
        f"/admin/api/users/{target.id}/password",
        json={"new_password": NEW_ADMIN_SET_PASSWORD},
        cookies={settings.SESSION_COOKIE_NAME: actor_cookie},
        follow_redirects=False,
    )

    assert response.status_code in {401, 403}
    unchanged = await _fetch_user_by_email(
        session_factory, "target@example.com"
    )
    assert unchanged is not None
    assert AuthService.verify_password(
        TEACHER_PASSWORD, unchanged.hashed_password
    )


@pytest.mark.asyncio
async def test_registration_template_collects_no_direct_pii_fields(client):
    response = await client.get(
        "/register?email=privacy@example.com", follow_redirects=False
    )

    assert response.status_code == 200
    body = response.text
    lowered = body.lower()
    assert 'action="/auth/register"' in lowered
    assert 'name="email"' in lowered
    assert 'name="password"' in lowered

    forbidden_inputs = [
        'name="name"',
        'name="full_name"',
        'name="nickname"',
        'name="phone"',
        'name="phone_number"',
        'name="mobile"',
        'id="name"',
        'id="nickname"',
        'id="phone"',
        'id="phone_number"',
        'id="mobile"',
    ]
    for forbidden in forbidden_inputs:
        assert forbidden not in lowered

    forbidden_labels = ["이름", "닉네임", "전화번호", "휴대폰"]
    for forbidden in forbidden_labels:
        assert forbidden not in body


@pytest.mark.asyncio
async def test_register_endpoint_is_whitelisted_for_browser_html_requests(
    client, session_factory
):
    """Browser-style POST /auth/register must not be intercepted by AuthMiddleware.

    A request carrying ``Accept: text/html`` is exactly what a real browser sends.
    If /auth/register is missing from ``WHITELIST_PATHS`` the middleware will
    redirect to ``/login`` — this test guards against that regression.
    """
    email = "browser_register@example.com"
    response = await client.post(
        "/auth/register",
        data={
            "email": email,
            "password": "TeacherPass123",
            "password_confirm": "TeacherPass123",
            "role": "teacher",
            "teacher_region": "서울",
            "teacher_career_years": "5",
        },
        headers={"Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )

    # Must redirect to dashboard, never to /login (the bug-class signature).
    assert response.status_code == 302
    location = response.headers["location"]
    assert location == "/"
    assert location != "/login"

    # Verify the User row was persisted.
    user = await _fetch_user_by_email(session_factory, email)
    assert user is not None
    assert user.email == email
    assert user.hashed_password is not None
    assert user.hashed_password != "TeacherPass123"
    assert not user.is_admin

    # Verify the UserProfile row exists with role="teacher".
    profile_model = _require_user_profile_model()
    async with session_factory() as session:
        result = await session.execute(
            select(profile_model).where(profile_model.user_id == user.id)
        )
    profile = result.scalar_one_or_none()
    assert profile is not None
    assert profile.role == "teacher"
