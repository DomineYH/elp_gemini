"""
Issue #90: 일반 사용자 인증/등록 전환 회귀 테스트.

Task 1 — 등록 폼에서 사용자 유형(role)/지역/경력 입력 제거.
Task 2 — 로그인 식별자를 email → 사용자 지정 id 로 전환.
  - id 형식: 영문+숫자, 9자 이하, 대소문자 무시 고유, 예약어 금지.

공개 HTTP 흐름 + DB 상태를 함께 검증한다.
"""
from __future__ import annotations

import base64
import inspect
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator

import itsdangerous
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
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
from app.routers import auth as auth_router
from app.routers.qna import _session_segment_label_for_user
from app.services.auth_service import AuthService

USER_ID = "teacher01"
USER_PASSWORD = "TeacherPass123"
ADMIN_PASSWORD = "AdminPass123"
NEW_ADMIN_SET_PASSWORD = "ChangedPass123"
ADMIN_CSRF_TOKEN = "test-admin-csrf-token"
TEMPLATE_DIR = Path("app/templates")


def _user_profile_exists_check():
    """Return UserProfile model if present (for negative profile asserts)."""
    try:
        from app.models.user_profiles import UserProfile
    except ModuleNotFoundError:
        return None
    return UserProfile


@pytest_asyncio.fixture
async def session_factory():
    """Per-test in-memory DB."""
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
    password: str,
    is_admin: bool = False,
) -> User:
    async with session_factory() as session:
        user = User(
            username=username,
            nickname=username,
            hashed_password=AuthService.hash_password(password),
            is_admin=is_admin,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _fetch_user_by_username(
    session_factory, username: str
) -> User | None:
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()


async def _register(
    client: AsyncClient,
    *,
    user_id: str = USER_ID,
    password: str = USER_PASSWORD,
    password_confirm: str | None = None,
):
    return await client.post(
        "/auth/register",
        data={
            "user_id": user_id,
            "password": password,
            "password_confirm": (
                password if password_confirm is None else password_confirm
            ),
        },
        headers={"Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )


def _register_route_request():
    return auth_router.Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/register",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "session": {},
        }
    )


def _assert_form_error(response):
    assert response.status_code in {200, 400, 409, 422}
    if response.status_code == 200:
        lowered = response.text.lower()
        assert "error" in lowered or "오류" in response.text


# ===== 등록 페이지/폼 (Task 1) =====


@pytest.mark.asyncio
async def test_register_page_collects_id_password_only(client):
    response = await client.get("/register", follow_redirects=False)

    assert response.status_code == 200
    body = response.text
    lowered = body.lower()
    assert 'action="/auth/register"' in lowered
    assert 'name="user_id"' in lowered
    assert 'name="password"' in lowered

    # Task 1: 유형/지역/경력 입력이 없어야 함
    forbidden = [
        'name="email"',
        'type="email"',
        'name="role"',
        'name="teacher_region"',
        'name="teacher_career_years"',
        'name="preservice_university_region"',
        'name="preservice_grade"',
    ]
    for token in forbidden:
        assert token not in lowered, token

    for label in ["사용자 유형", "지역", "경력", "학년"]:
        assert label not in body, label


def test_register_password_confirm_form_field_is_required():
    param = inspect.signature(
        auth_router.register_user
    ).parameters["password_confirm"]

    assert param.annotation is str
    assert param.default.is_required()


@pytest.mark.asyncio
async def test_register_creates_id_user_without_profile(
    client, session_factory
):
    response = await _register(client)

    assert response.status_code == 302
    assert response.headers["location"] == "/"

    user = await _fetch_user_by_username(session_factory, USER_ID)
    assert user is not None
    assert user.username == USER_ID
    assert user.nickname == USER_ID  # nickname = id
    assert not user.is_admin
    assert user.hashed_password != USER_PASSWORD
    assert AuthService.verify_password(USER_PASSWORD, user.hashed_password)

    # Task 1: UserProfile 행이 생성되지 않아야 함
    profile_model = _user_profile_exists_check()
    if profile_model is not None:
        async with session_factory() as session:
            result = await session.execute(
                select(profile_model).where(
                    profile_model.user_id == user.id
                )
            )
            assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_register_normalizes_id_to_lowercase(client, session_factory):
    response = await _register(client, user_id="AbC123")
    assert response.status_code == 302

    assert await _fetch_user_by_username(session_factory, "abc123") is not None
    assert await _fetch_user_by_username(session_factory, "AbC123") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_id",
    [
        "abcdefghij",  # 10자 (9자 초과)
        "ab_12",  # 밑줄
        "ab-12",  # 하이픈
        "ab 12",  # 공백
        "한글",  # 비ASCII
        "",  # 빈값
        "admin",  # 예약어
        "administrator",  # 예약어
        "root",  # 예약어
        "system",  # 예약어
        "teacher",  # legacy role id 예약어
        "preservice_teacher",  # legacy role id 예약어
        "ADMIN",  # 정규화(소문자) 후 예약어
    ],
)
async def test_register_rejects_invalid_id(client, session_factory, bad_id):
    response = await _register(client, user_id=bad_id)

    _assert_form_error(response)
    normalized = bad_id.strip().lower()
    if normalized:
        assert (
            await _fetch_user_by_username(session_factory, normalized) is None
        )


@pytest.mark.asyncio
async def test_register_duplicate_id_rejected_case_insensitive(
    client, session_factory
):
    first = await _register(client, user_id="dupuser")
    assert first.status_code == 302

    # 대소문자만 다른 동일 id 는 거부되어야 함
    second = await _register(client, user_id="DupUser")
    assert second.status_code in {400, 409}

    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == "dupuser")
        )
        assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_register_rejects_existing_admin_username(
    client, session_factory
):
    """사용자 지정 id 는 기존 관리자 username 과도 충돌하면 안 된다.

    예약어가 아니지만 id 패턴에 부합하는 관리자 username('Teacher5')을
    누군가 점유하려는 시도를 전체 네임스페이스 중복검사가 막아야 한다.
    """
    await _create_user(
        session_factory,
        username="Teacher5",
        password=ADMIN_PASSWORD,
        is_admin=True,
    )

    response = await _register(client, user_id="teacher5")  # 대소문자 무시

    assert response.status_code in {400, 409}
    assert settings.SESSION_COOKIE_NAME not in response.cookies

    # 'teacher5' 행은 관리자 하나만 존재하고 변경되지 않아야 함
    async with session_factory() as session:
        result = await session.execute(select(User))
        rows = [
            user for user in result.scalars().all()
            if user.username.lower() == "teacher5"
        ]
    assert len(rows) == 1
    assert rows[0].is_admin is True
    assert rows[0].username == "Teacher5"


@pytest.mark.asyncio
async def test_register_duplicate_id_query_is_case_insensitive():
    class ExistingUserResult:
        def scalar_one_or_none(self):
            return User(username="Teacher5")

    class EmptyResult:
        def scalar_one_or_none(self):
            return None

    class RecordingDb:
        def __init__(self):
            self.sql = []

        async def execute(self, statement):
            compiled = str(
                statement.compile(compile_kwargs={"literal_binds": True})
            )
            self.sql.append(compiled)
            if "lower(" in compiled.lower():
                return ExistingUserResult()
            return EmptyResult()

    db = RecordingDb()
    service = AuthService(db)

    with pytest.raises(ValueError, match="이미 사용 중인 아이디"):
        await service.register_regular_user("teacher5", USER_PASSWORD)

    assert any("lower(" in sql.lower() for sql in db.sql)


@pytest.mark.asyncio
async def test_register_password_mismatch_rejected(client, session_factory):
    response = await _register(
        client, user_id="mismatch", password_confirm="DifferentPass123"
    )
    _assert_form_error(response)
    assert "비밀번호 확인이 일치하지 않습니다." in response.text
    assert await _fetch_user_by_username(session_factory, "mismatch") is None


@pytest.mark.asyncio
async def test_register_password_mismatch_returns_error_directly():
    response = await auth_router.register_user(
        _register_route_request(),
        user_id="mismatch",
        password=USER_PASSWORD,
        password_confirm="DifferentPass123",
        db=object(),
    )

    assert response.status_code == 400
    assert response.context["error"] == "비밀번호 확인이 일치하지 않습니다."


@pytest.mark.asyncio
async def test_register_matching_password_confirm_succeeds_directly(
    monkeypatch,
):
    request = _register_route_request()
    user = SimpleNamespace(
        id=77,
        username="matchok",
        nickname="matchok",
        is_admin=False,
    )

    async def register_regular_user(self, user_id, password):
        assert user_id == "matchok"
        assert password == USER_PASSWORD
        return user

    monkeypatch.setattr(
        AuthService, "register_regular_user", register_regular_user
    )

    response = await auth_router.register_user(
        request,
        user_id="matchok",
        password=USER_PASSWORD,
        password_confirm=USER_PASSWORD,
        db=object(),
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert request.session["user_id"] == user.id
    assert request.session["username"] == user.username


@pytest.mark.asyncio
@pytest.mark.parametrize("weak", ["short1", "nodigitshere", "12345678"])
async def test_register_weak_password_rejected(
    client, session_factory, weak
):
    response = await _register(client, user_id="weakpw", password=weak)
    _assert_form_error(response)
    assert await _fetch_user_by_username(session_factory, "weakpw") is None


# ===== 로그인 (Task 2) =====


@pytest.mark.asyncio
async def test_login_page_uses_id_not_email(client):
    response = await client.get("/login", follow_redirects=False)

    assert response.status_code == 200
    lowered = response.text.lower()
    assert 'action="/auth/login/user"' in lowered
    assert 'name="user_id"' in lowered
    assert 'name="password"' in lowered
    assert 'type="email"' not in lowered
    assert 'name="email"' not in lowered
    assert "초대 코드" not in response.text


def test_login_template_allows_legacy_email_identifier_submission():
    source = (TEMPLATE_DIR / "user/login.html").read_text(
        encoding="utf-8"
    )

    assert 'name="user_id"' in source
    assert 'type="email"' not in source
    assert 'maxlength="9"' not in source
    assert 'pattern="[A-Za-z0-9]{1,9}"' not in source


@pytest.mark.asyncio
async def test_login_with_id_sets_session(client, session_factory):
    user = await _create_user(
        session_factory, username=USER_ID, password=USER_PASSWORD
    )

    response = await client.post(
        "/auth/login/user",
        data={"user_id": USER_ID, "password": USER_PASSWORD},
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["location"] == "/"
    cookie = response.cookies.get(settings.SESSION_COOKIE_NAME)
    assert cookie is not None
    session = _decode_session_cookie(cookie)
    assert session["user_id"] == user.id
    assert session["is_admin"] is False
    assert session["username"] == USER_ID


@pytest.mark.asyncio
async def test_login_id_is_case_insensitive(client, session_factory):
    await _create_user(
        session_factory, username="caseuser", password=USER_PASSWORD
    )

    response = await client.post(
        "/auth/login/user",
        data={"user_id": "CaseUser", "password": USER_PASSWORD},
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["location"] == "/"


@pytest.mark.asyncio
async def test_login_rejects_invalid_id_before_user_lookup(monkeypatch):
    bad_id = "teacher_550e8400e29b41d4a716446655440000"
    auth_events = []
    request = auth_router.Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login/user",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "session": {},
        }
    )

    def record_auth_event(event_type, **kwargs):
        auth_events.append((event_type, kwargs))

    async def fail_if_lookup_runs(self, user_id, password):
        raise AssertionError("invalid login id must not reach user lookup")

    monkeypatch.setattr(auth_router, "log_auth_event", record_auth_event)
    monkeypatch.setattr(
        AuthService,
        "authenticate_regular_user_by_username",
        fail_if_lookup_runs,
    )

    response = await auth_router.login_user(
        request,
        user_id=bad_id,
        password=USER_PASSWORD,
        db=object(),
    )

    assert response.status_code == 401
    assert request.session == {}
    assert response.context["error"] == (
        auth_router.INVALID_USER_CREDENTIALS_MESSAGE
    )
    assert "영문/숫자" not in response.context["error"]
    assert auth_events == [
        (
            "login",
            {
                "username": bad_id,
                "success": False,
                "reason": "Invalid regular-user credentials",
            },
        )
    ]


@pytest.mark.asyncio
async def test_regular_user_login_lookup_query_is_case_insensitive():
    class EmptyResult:
        def scalar_one_or_none(self):
            return None

    class RecordingDb:
        def __init__(self):
            self.sql = []

        async def execute(self, statement):
            compiled = str(
                statement.compile(compile_kwargs={"literal_binds": True})
            )
            self.sql.append(compiled)
            return EmptyResult()

    db = RecordingDb()
    service = AuthService(db)

    assert await service.get_regular_user_by_username("Teacher5") is None

    assert any("lower(" in sql.lower() for sql in db.sql)
    assert any("is_admin IS false" in sql for sql in db.sql)


@pytest.mark.asyncio
async def test_login_wrong_password_no_session(client, session_factory):
    await _create_user(
        session_factory, username=USER_ID, password=USER_PASSWORD
    )

    response = await client.post(
        "/auth/login/user",
        data={"user_id": USER_ID, "password": "WrongPass123"},
        follow_redirects=False,
    )

    assert response.status_code in {400, 401}
    assert settings.SESSION_COOKIE_NAME not in response.cookies


@pytest.mark.asyncio
async def test_unknown_id_does_not_redirect_to_register(client):
    """미등록 id 는 등록 화면으로 자동 리다이렉트하지 않는다 (id 열거 방지)."""
    response = await client.post(
        "/auth/login/user",
        data={"user_id": "nobody1", "password": USER_PASSWORD},
        follow_redirects=False,
    )

    assert response.status_code in {400, 401}
    assert settings.SESSION_COOKIE_NAME not in response.cookies


@pytest.mark.asyncio
async def test_admin_cannot_authenticate_via_user_route(
    client, session_factory
):
    """관리자 계정은 일반 사용자 로그인 경로로 인증되지 않아야 한다."""
    await _create_user(
        session_factory,
        username="admin",
        password=ADMIN_PASSWORD,
        is_admin=True,
    )

    response = await client.post(
        "/auth/login/user",
        data={"user_id": "admin", "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )

    assert response.status_code in {400, 401}
    assert settings.SESSION_COOKIE_NAME not in response.cookies


@pytest.mark.asyncio
async def test_legacy_username_login_no_longer_creates_session(
    client, session_factory
):
    response = await client.post(
        "/auth/login",
        data={"username": "legacy_user", "nickname": "Legacy"},
        follow_redirects=False,
    )

    assert response.status_code == 410
    assert settings.SESSION_COOKIE_NAME not in response.cookies
    assert (
        await _fetch_user_by_username(session_factory, "legacy_user") is None
    )


# ===== id-only 사용자 표시/분석 세그먼트 =====


@pytest.mark.asyncio
async def test_qna_session_segment_for_id_only_user_is_neutral():
    class EmptyProfileResult:
        def scalar_one_or_none(self):
            return None

    class EmptyProfileSession:
        async def execute(self, statement):
            return EmptyProfileResult()

    user = User(
        username=USER_ID,
        nickname=USER_ID,
        hashed_password="hashed",
        is_admin=False,
    )
    user.id = 1

    label = await _session_segment_label_for_user(EmptyProfileSession(), user)

    assert label == "미지정"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("nickname", "expected_label"),
    [
        ("teacher", "교사"),
        ("1학년", "1학년"),
        ("2학년", "2학년"),
        ("3학년", "3학년"),
        ("4학년", "4학년"),
        ("교사", "교사"),
        ("preservice_teacher", "미지정"),
    ],
)
async def test_qna_session_segment_keeps_legacy_profileless_segment_nicknames(
    nickname, expected_label
):
    class EmptyProfileResult:
        def scalar_one_or_none(self):
            return None

    class EmptyProfileSession:
        async def execute(self, statement):
            return EmptyProfileResult()

    user = User(
        username=f"{nickname}_abc123",
        nickname=nickname,
        hashed_password="hashed",
        is_admin=False,
    )
    user.id = 1

    label = await _session_segment_label_for_user(EmptyProfileSession(), user)

    assert label == expected_label


def test_user_nav_templates_fall_back_to_id_when_email_missing():
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    user = SimpleNamespace(nickname=USER_ID)
    document = SimpleNamespace(
        id=1,
        title="lesson.pdf",
        file_size=1024,
        uploaded_at=datetime(2026, 1, 2, 3, 4),
        status="ready",
    )
    contexts = {
        "user/dashboard.html": {
            "user": user,
            "criteria_documents": [],
        },
        "user/viewer.html": {
            "user": user,
            "document": document,
        },
        "user/doc_detail.html": {
            "user": user,
            "document": document,
            "extracted_text": "",
        },
        "user/eval_report.html": {
            "user": user,
            "document_id": 1,
        },
    }

    for template_name, context in contexts.items():
        rendered = env.get_template(template_name).render(**context)

        assert f">{USER_ID}<" in rendered, template_name
        assert ">None<" not in rendered, template_name


# ===== 관리자 비밀번호 재설정 (email 제거 영향) =====


class _PasswordChangeResult:
    def __init__(self, user):
        self.user = user

    def scalar_one_or_none(self):
        return self.user


class _PasswordChangeDb:
    def __init__(self, user):
        self.user = user
        self.committed = False
        self.refreshed_user = None

    async def execute(self, statement):
        return _PasswordChangeResult(self.user)

    async def commit(self):
        self.committed = True

    async def refresh(self, user):
        self.refreshed_user = user


@pytest.mark.asyncio
async def test_admin_rejects_password_change_for_non_login_capable_user(
    monkeypatch,
):
    """로그인 식별자가 없는 레거시 계정은 재설정 성공처럼 보이면 안 된다."""
    user = SimpleNamespace(
        id=91,
        username="legacy-invite-code",
        nickname="legacy",
        is_admin=False,
        hashed_password="old-hash",
        failed_login_count=2,
        locked_until=datetime(2026, 6, 4, 9, 0, 0),
        last_failed_login_at=datetime(2026, 6, 4, 8, 0, 0),
    )
    db = _PasswordChangeDb(user)
    monkeypatch.setattr(
        AuthService,
        "hash_password",
        staticmethod(lambda password: "new-hash"),
    )

    with pytest.raises(ValueError, match="로그인 가능한"):
        await AuthService(db).admin_set_user_password(
            user.id, NEW_ADMIN_SET_PASSWORD
        )

    assert db.committed is False
    assert db.refreshed_user is None
    assert user.hashed_password == "old-hash"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "username",
    [
        "validid1",
    ],
)
async def test_admin_can_change_password_for_login_capable_users(
    monkeypatch, username
):
    user = SimpleNamespace(
        id=92,
        username=username,
        nickname=username,
        is_admin=False,
        hashed_password="old-hash",
        failed_login_count=2,
        locked_until=datetime(2026, 6, 4, 9, 0, 0),
        last_failed_login_at=datetime(2026, 6, 4, 8, 0, 0),
    )
    db = _PasswordChangeDb(user)
    monkeypatch.setattr(
        AuthService,
        "hash_password",
        staticmethod(lambda password: "new-hash"),
    )

    changed = await AuthService(db).admin_set_user_password(
        user.id, NEW_ADMIN_SET_PASSWORD
    )

    assert changed is user
    assert db.committed is True
    assert db.refreshed_user is user
    assert user.hashed_password == "new-hash"
    assert user.failed_login_count == 0
    assert user.locked_until is None
    assert user.last_failed_login_at is None


@pytest.mark.asyncio
async def test_admin_can_change_id_only_user_password(
    client, session_factory
):
    """email 이 없는 id 기반 사용자도 관리자 비밀번호 재설정이 가능해야 한다."""
    admin = await _create_user(
        session_factory,
        username="adminmgr",
        password=ADMIN_PASSWORD,
        is_admin=True,
    )
    regular = await _create_user(
        session_factory, username="managed1", password=USER_PASSWORD
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
    changed = await _fetch_user_by_username(session_factory, "managed1")
    assert changed is not None
    assert AuthService.verify_password(
        NEW_ADMIN_SET_PASSWORD, changed.hashed_password
    )

    new_login = await client.post(
        "/auth/login/user",
        data={"user_id": "managed1", "password": NEW_ADMIN_SET_PASSWORD},
        follow_redirects=False,
    )
    assert new_login.status_code in {302, 303}


@pytest.mark.asyncio
async def test_admin_password_change_requires_csrf_token(
    client, session_factory
):
    admin = await _create_user(
        session_factory,
        username="admincsrf",
        password=ADMIN_PASSWORD,
        is_admin=True,
    )
    regular = await _create_user(
        session_factory, username="csrftgt", password=USER_PASSWORD
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
    unchanged = await _fetch_user_by_username(session_factory, "csrftgt")
    assert AuthService.verify_password(
        USER_PASSWORD, unchanged.hashed_password
    )


@pytest.mark.asyncio
async def test_admin_password_change_uses_shared_password_policy(
    client, session_factory
):
    admin = await _create_user(
        session_factory,
        username="adminpol",
        password=ADMIN_PASSWORD,
        is_admin=True,
    )
    regular = await _create_user(
        session_factory, username="weaktgt", password=USER_PASSWORD
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
    unchanged = await _fetch_user_by_username(session_factory, "weaktgt")
    assert AuthService.verify_password(
        USER_PASSWORD, unchanged.hashed_password
    )


@pytest.mark.asyncio
async def test_non_admin_cannot_change_user_password(
    client, session_factory
):
    actor = await _create_user(
        session_factory, username="actor1", password=USER_PASSWORD
    )
    target = await _create_user(
        session_factory, username="target1", password=USER_PASSWORD
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
    unchanged = await _fetch_user_by_username(session_factory, "target1")
    assert AuthService.verify_password(
        USER_PASSWORD, unchanged.hashed_password
    )
