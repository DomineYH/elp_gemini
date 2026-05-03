"""
Issue #5: 관리자 로그인 brute-force 방어 회귀 테스트

검증 매트릭스:
    .omc/plans/2026-04-29-issue-5-admin-bruteforce-protection.md §3
    AC1  IP rate limit 초과 시 429 응답
    AC2  N회 실패 시 (N+1)번째 lockout
    AC3  lockout 만료 후 정상 인증 + 카운터 리셋
    AC4  성공 시 카운터/잠금 정보 리셋
    AC5  failed_login_count / locked_until / last_failed_login_at 영속화
    AC6  lockout 중 verify_password 호출 안 함 (timing leak 차단)
    AC7  존재하지 않는 admin_id 도 동일 메시지
    AC8  lockout_triggered / lockout_attempt_blocked 감사 로그
    +    동시 실패 요청에서 failed_login_count lost-update 없음 (Codex P2 후속)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import AsyncIterator
from unittest.mock import patch

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

ADMIN_USERNAME = "bf_admin"
ADMIN_PASSWORD = "correct horse battery staple"


@pytest_asyncio.fixture
async def db_engine():
    """각 테스트마다 격리된 in-memory DB 엔진."""
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
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    return factory


@pytest_asyncio.fixture
async def admin_user(session_factory) -> User:
    """관리자 1명을 사전 생성하고 반환한다."""
    from app.services.auth_service import AuthService

    async with session_factory() as session:
        hashed = AuthService.hash_password(ADMIN_PASSWORD)
        user = User(
            username=ADMIN_USERNAME,
            nickname="bf_admin",
            email=None,
            hashed_password=hashed,
            is_admin=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def http_client(session_factory) -> AsyncIterator[AsyncClient]:
    """get_db 를 테스트 세션으로 오버라이드한 ASGI 클라이언트."""

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
    """각 테스트 전후로 slowapi storage 초기화."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def disable_rate_limit():
    """rate limit 비활성화 (lockout / 메시지 테스트용)."""
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _post_login(client: AsyncClient, admin_id: str, password: str):
    return client.post(
        "/auth/login/admin",
        data={"admin_id": admin_id, "password": password},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------
# AC1 — IP rate limit
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ip_rate_limit_returns_429(http_client, admin_user):
    """동일 IP에서 짧은 시간 내 5회를 초과하면 429."""
    # rate limit 활성화 상태가 기본 (enabled=True)
    limiter.enabled = True
    statuses = []
    for _ in range(8):
        resp = await _post_login(
            http_client, ADMIN_USERNAME, "wrong"
        )
        statuses.append(resp.status_code)
    assert 429 in statuses, (
        f"6번째 이후 요청이 429를 반환해야 함: {statuses}"
    )


# ---------------------------------------------------------------------
# AC2 — N회 실패 후 잠금
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_account_locks_after_threshold(
    http_client, admin_user, session_factory, disable_rate_limit
):
    """기본 임계치(10회) 실패 후 잠금 메시지를 반환."""
    from app.config import settings

    threshold = settings.ADMIN_MAX_FAILED_ATTEMPTS

    for _ in range(threshold):
        resp = await _post_login(
            http_client, ADMIN_USERNAME, "wrong"
        )
        assert resp.status_code == 401

    # 임계치 도달 시점에 lockout 메시지로 전환되어야 함
    resp = await _post_login(
        http_client, ADMIN_USERNAME, "wrong"
    )
    assert resp.status_code == 401
    # issue #6: lockout 응답이 외부에는 invalid-credentials 와 동일해야 함
    assert "ID 또는 비밀번호" in resp.text, (
        "lockout 시에도 invalid 와 동일한 메시지여야 함 (#6)"
    )
    assert "잠시" not in resp.text, (
        "lockout 임을 외부에 누설하면 안 됨 (#6)"
    )

    # DB에 잠금 정보가 영속화되어 있어야 함
    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        assert user.failed_login_count >= threshold
        assert user.locked_until is not None
        assert user.locked_until > datetime.utcnow()


# ---------------------------------------------------------------------
# AC3 — 잠금 만료 후 정상 동작
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lockout_expires_allows_login(
    http_client, admin_user, session_factory, disable_rate_limit
):
    """locked_until 이 과거가 되면 잠금이 풀린다."""
    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        user.failed_login_count = 10
        user.locked_until = datetime.utcnow() - timedelta(seconds=1)
        await session.commit()

    resp = await _post_login(
        http_client, ADMIN_USERNAME, ADMIN_PASSWORD
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin/dashboard"

    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        assert user.failed_login_count == 0
        assert user.locked_until is None
        assert user.last_failed_login_at is None


# ---------------------------------------------------------------------
# AC4 — 성공 시 카운터 리셋
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_successful_login_resets_counter(
    http_client, admin_user, session_factory, disable_rate_limit
):
    # 임계치 미만 실패 누적
    for _ in range(3):
        resp = await _post_login(
            http_client, ADMIN_USERNAME, "wrong"
        )
        assert resp.status_code == 401

    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        assert user.failed_login_count == 3

    resp = await _post_login(
        http_client, ADMIN_USERNAME, ADMIN_PASSWORD
    )
    assert resp.status_code == 302

    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        assert user.failed_login_count == 0
        assert user.locked_until is None
        assert user.last_failed_login_at is None


# ---------------------------------------------------------------------
# AC5 — 컬럼 영속화 (실패 누적이 DB에 기록됨)
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_attempts_persisted(
    http_client, admin_user, session_factory, disable_rate_limit
):
    await _post_login(http_client, ADMIN_USERNAME, "wrong")
    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        assert user.failed_login_count == 1
        assert user.last_failed_login_at is not None
        assert user.locked_until is None  # 임계치 전에는 None


# ---------------------------------------------------------------------
# AC6 — 잠긴 계정은 verify_password 를 거치지 않는다
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_locked_account_skips_password_verification(
    http_client, admin_user, session_factory, disable_rate_limit
):
    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        user.failed_login_count = 10
        user.locked_until = datetime.utcnow() + timedelta(minutes=5)
        await session.commit()

    with patch(
        "app.services.auth_service.AuthService.verify_password"
    ) as verify:
        verify.return_value = True
        resp = await _post_login(
            http_client, ADMIN_USERNAME, ADMIN_PASSWORD
        )
        assert resp.status_code == 401
        # issue #6: 외부 메시지는 invalid 와 동일, 단 real verify_password 는
        # 호출되지 않아 timing 절약 + 사이드이펙트 차단 (AC6 의도 유지).
        assert "ID 또는 비밀번호" in resp.text
        verify.assert_not_called()


# ---------------------------------------------------------------------
# AC7 — 존재하지 않는 admin_id 도 동일 메시지
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unknown_admin_returns_generic_message(
    http_client, admin_user, disable_rate_limit
):
    resp_unknown = await _post_login(
        http_client, "no_such_admin", "wrong"
    )
    resp_known = await _post_login(
        http_client, ADMIN_USERNAME, "wrong"
    )
    assert resp_unknown.status_code == resp_known.status_code == 401
    # 동일한 일반 실패 메시지가 노출되어야 함
    assert "ID 또는 비밀번호" in resp_unknown.text
    assert "ID 또는 비밀번호" in resp_known.text
    # 사용자 존재 여부를 누설하는 잠금 메시지는 노출되지 않아야 함
    assert "잠시" not in resp_unknown.text


# ---------------------------------------------------------------------
# AC8 — 감사 로그
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_log_records_lockout_events(
    http_client, admin_user, session_factory, disable_rate_limit, caplog
):
    from app.config import settings

    threshold = settings.ADMIN_MAX_FAILED_ATTEMPTS

    caplog.set_level("INFO", logger="app.auth")
    caplog.set_level("WARNING", logger="app.auth")

    for _ in range(threshold):
        await _post_login(http_client, ADMIN_USERNAME, "wrong")

    # 잠긴 상태에서 추가 시도
    await _post_login(http_client, ADMIN_USERNAME, "wrong")

    audit_messages = [r.getMessage() for r in caplog.records]
    joined = "\n".join(audit_messages)
    assert "lockout_triggered" in joined, joined
    assert "lockout_attempt_blocked" in joined, joined
    assert "failed_attempt=" in joined, joined


# ---------------------------------------------------------------------
# Codex P2 후속 — 동시 실패 요청에서 failed_login_count 가 정확히 누적
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_failed_logins_no_lost_updates(
    admin_user, session_factory, disable_rate_limit
):
    """10개 코루틴이 각자 별도 세션으로 동시에 실패 시도해도
    failed_login_count == 10 이어야 한다 (atomic UPDATE 검증)."""
    from app.services.auth_service import AuthService

    async def fail_once() -> None:
        async with session_factory() as session:
            service = AuthService(session)
            result = await service.authenticate_admin(
                ADMIN_USERNAME, "wrong"
            )
            # 임계치(10) 도달 전까지는 not locked, 도달 후엔 locked 가능
            assert result.user is None

        return None

    await asyncio.gather(*[fail_once() for _ in range(10)])

    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        assert user.failed_login_count == 10, (
            f"동시 10회 실패 후 카운터가 {user.failed_login_count}"
            f" — lost update 의심"
        )
        assert user.locked_until is not None, (
            "임계치 도달했으므로 locked_until 이 설정되어야 함"
        )
        assert user.locked_until > datetime.utcnow()


# ---------------------------------------------------------------------
# Codex round-2 P2 — 만료된 lockout 후 실패 시 카운터 리셋 + 스테일 lockout 정리
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_expired_lockout_resets_window(
    admin_user, session_factory, disable_rate_limit
):
    """locked_until 이 과거가 된 후 잘못된 비밀번호로 로그인하면
    failed_login_count 가 1 로 리셋되고 stale locked_until 이
    정리되어야 한다."""
    from app.services.auth_service import AuthService

    # given: 이전에 잠긴 적 있고, lockout 이 만료된 상태
    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        user.failed_login_count = 10
        user.locked_until = datetime.utcnow() - timedelta(seconds=1)
        await session.commit()

    # when: 만료 후 잘못된 비밀번호로 로그인 시도
    async with session_factory() as session:
        service = AuthService(session)
        result = await service.authenticate_admin(
            ADMIN_USERNAME, "wrong"
        )
        assert result.user is None
        assert result.locked is False

    # then: 카운터는 1 로 리셋, stale locked_until 은 None,
    #       last_failed_login_at 은 갱신
    async with session_factory() as session:
        user = await session.get(User, admin_user.id)
        assert user.failed_login_count == 1, (
            f"만료된 lockout 후 첫 실패는 failed_login_count=1 이어야 함 "
            f"(실제: {user.failed_login_count})"
        )
        assert user.locked_until is None, (
            f"stale locked_until 이 정리되어야 함 "
            f"(실제: {user.locked_until})"
        )
        assert user.last_failed_login_at is not None


# ---------------------------------------------------------------------
# 보너스 — rate-limit 비활성화 시 429 가 절대 발생하지 않는다 (AC10 보조)
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rate_limit_disabled_returns_no_429(
    http_client, admin_user, disable_rate_limit
):
    statuses = []
    for _ in range(15):
        resp = await _post_login(
            http_client, ADMIN_USERNAME, "wrong"
        )
        statuses.append(resp.status_code)
    assert 429 not in statuses, (
        f"rate limit 비활성화 시 429 가 나오면 안 됨: {statuses}"
    )
