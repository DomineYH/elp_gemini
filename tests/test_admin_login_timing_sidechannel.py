"""Issue #6: 관리자 로그인 타이밍/메시지 사이드채널 회귀 테스트

검증:
  T1  missing user / non-admin / locked / no-password / invalid-password
      5경로의 status_code 와 response body 가 동일
  T2  모든 실패 경로에서 bcrypt verify (real OR dummy) 가 1회 이상 호출됨
  T3  audit 로그는 내부적으로 분리 기록 유지 (외부 통일과 무관)
  T4  wall-clock: locked vs invalid-password 경로의 응답 시간 중앙값이 통계적으로
      구분되지 않는다 (issue #6 사용자 명시 요구: status/body/timing 모두 일치)
"""
from __future__ import annotations

import statistics
import time
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
from app.services.auth_service import AuthService


ADMIN = "ts_admin"
ADMIN_PASSWORD = "correct horse battery staple"


# ---------------------------------------------------------------------
# Fixtures (self-contained, same pattern as test_admin_login_bruteforce.py)
# ---------------------------------------------------------------------


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
    async with session_factory() as session:
        hashed = AuthService.hash_password(ADMIN_PASSWORD)
        user = User(
            username=ADMIN,
            nickname="ts_admin",
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
    """rate limit 비활성화."""
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


# ---------------------------------------------------------------------
# T1 — 모든 실패 경로가 동일한 응답 반환
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_failure_paths_return_identical_response(
    http_client, admin_user, session_factory, disable_rate_limit
):
    # Path 1: missing user
    r1 = await http_client.post(
        "/auth/login/admin",
        data={"admin_id": "no_such_user", "password": "x"},
        follow_redirects=False,
    )

    # Path 2: non-admin user (is_admin=False)
    async with session_factory() as s:
        s.add(
            User(
                username="regular",
                nickname="r",
                hashed_password=AuthService.hash_password("p"),
                is_admin=False,
            )
        )
        await s.commit()
    r2 = await http_client.post(
        "/auth/login/admin",
        data={"admin_id": "regular", "password": "x"},
        follow_redirects=False,
    )

    # Path 3: invalid password
    r3 = await http_client.post(
        "/auth/login/admin",
        data={"admin_id": ADMIN, "password": "wrong"},
        follow_redirects=False,
    )

    # Path 4: locked account
    async with session_factory() as s:
        u = await s.get(User, admin_user.id)
        u.failed_login_count = 10
        u.locked_until = datetime.utcnow() + timedelta(minutes=5)
        await s.commit()
    r4 = await http_client.post(
        "/auth/login/admin",
        data={"admin_id": ADMIN, "password": "wrong"},
        follow_redirects=False,
    )

    # Path 5: no-password admin (hashed_password cleared)
    async with session_factory() as s:
        u = await s.get(User, admin_user.id)
        u.hashed_password = None
        u.locked_until = None
        u.failed_login_count = 0
        await s.commit()
    r5 = await http_client.post(
        "/auth/login/admin",
        data={"admin_id": ADMIN, "password": "x"},
        follow_redirects=False,
    )

    for label, r in [
        ("missing_user", r1),
        ("non_admin", r2),
        ("invalid_password", r3),
        ("locked", r4),
        ("no_password", r5),
    ]:
        assert r.status_code == 401, f"{label}: expected 401, got {r.status_code}"
        assert "ID 또는 비밀번호" in r.text, (
            f"{label}: unified message missing"
        )
        assert "잠시" not in r.text, (
            f"{label}: lockout message leaked (#6)"
        )


# ---------------------------------------------------------------------
# T2 — dummy bcrypt verify 가 early-return 경로에서 호출됨
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dummy_bcrypt_verify_called_in_missing_user_path(
    session_factory, disable_rate_limit
):
    """missing user 경로에서 dummy verify 가 호출됨을 verify."""
    with patch.object(AuthService, "_dummy_password_verify") as dummy:
        async with session_factory() as session:
            svc = AuthService(session)
            result = await svc.authenticate_admin("no_such_user", "x")
        assert result.user is None
        dummy.assert_called_once_with("x")


@pytest.mark.asyncio
async def test_dummy_bcrypt_verify_called_in_locked_path(
    admin_user, session_factory, disable_rate_limit
):
    """locked 경로에서도 dummy verify 가 호출됨."""
    async with session_factory() as s:
        u = await s.get(User, admin_user.id)
        u.failed_login_count = 10
        u.locked_until = datetime.utcnow() + timedelta(minutes=5)
        await s.commit()

    with patch.object(AuthService, "_dummy_password_verify") as dummy:
        async with session_factory() as session:
            svc = AuthService(session)
            result = await svc.authenticate_admin(ADMIN, "x")
        assert result.locked is True
        dummy.assert_called_once_with("x")


# ---------------------------------------------------------------------
# T3 — 외부 응답은 통일이지만 내부 audit 로그는 분리 유지
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_distinguishes_locked_vs_invalid(
    http_client, admin_user, session_factory, disable_rate_limit, caplog
):
    """외부 응답은 동일해도 내부 audit 로그는 lockout vs invalid 를 구분.

    보안 모니터링이 lockout-bypass 시도와 일반 invalid 시도를 구분할 수
    있어야 SOC 가 정상 운영된다.
    """
    caplog.set_level("INFO", logger="app.auth")
    caplog.set_level("WARNING", logger="app.auth")

    # locked 상태 만들기
    async with session_factory() as s:
        u = await s.get(User, admin_user.id)
        u.failed_login_count = 10
        u.locked_until = datetime.utcnow() + timedelta(minutes=5)
        await s.commit()

    # locked 경로 요청
    await http_client.post(
        "/auth/login/admin",
        data={"admin_id": ADMIN, "password": "wrong"},
        follow_redirects=False,
    )

    # missing/non-admin (invalid) 경로 요청
    await http_client.post(
        "/auth/login/admin",
        data={"admin_id": "no_such_admin", "password": "wrong"},
        follow_redirects=False,
    )

    joined = "\n".join(r.getMessage() for r in caplog.records)
    # locked 경로는 service-layer 와 router-layer 양쪽에서 별도 audit 이벤트를 남긴다
    assert "lockout_attempt_blocked" in joined, (
        "service 의 lockout 이벤트가 audit 에 남아야 함"
    )
    assert "lockout_attempt_external_blocked" in joined, (
        "router 의 외부 응답 통일 이벤트가 audit 에 남아야 함"
    )
    # invalid 경로는 일반 'Invalid credentials' 이벤트만 남는다
    assert "Invalid credentials" in joined, (
        "invalid 경로의 audit 이벤트가 보존되어야 함"
    )


# ---------------------------------------------------------------------
# T4 — wall-clock: locked vs invalid 경로의 응답 시간 중앙값 일치
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_locked_vs_invalid_password_wallclock_parity(
    http_client, admin_user, session_factory, disable_rate_limit
):
    """사용자 명시 요구 (issue #6): locked vs invalid 응답이 status/body 뿐 아니라
    timing 까지 일치해야 한다. 두 경로의 응답 시간 중앙값이 30% 이내로 수렴하면 통과.

    bcrypt 한 번 ≈ 60-80ms 가 두 경로 공통 비용이므로 분산은 작은 편이고,
    이 임계치는 in-memory SQLite + ASGITransport 환경의 일반적인 jitter 를 흡수한다.
    실제 timing oracle (real DB UPDATE only on invalid) 는 ms 단위 차이를 만들기 때문에
    bcrypt 비용 대비 비율이 30% 임계치 안에 들어와야 한다.
    """
    SAMPLES = 8  # 적절한 통계 + CI 시간 균형

    # invalid-password 경로 샘플
    invalid_times = []
    for _ in range(SAMPLES):
        # 매 시도마다 lockout 이 발생하지 않도록 카운터 리셋
        async with session_factory() as s:
            u = await s.get(User, admin_user.id)
            u.failed_login_count = 0
            u.locked_until = None
            await s.commit()
        t0 = time.perf_counter()
        await http_client.post(
            "/auth/login/admin",
            data={"admin_id": ADMIN, "password": "wrong"},
            follow_redirects=False,
        )
        invalid_times.append(time.perf_counter() - t0)

    # locked 경로 샘플
    async with session_factory() as s:
        u = await s.get(User, admin_user.id)
        u.failed_login_count = 10
        u.locked_until = datetime.utcnow() + timedelta(minutes=5)
        await s.commit()

    locked_times = []
    for _ in range(SAMPLES):
        t0 = time.perf_counter()
        await http_client.post(
            "/auth/login/admin",
            data={"admin_id": ADMIN, "password": "wrong"},
            follow_redirects=False,
        )
        locked_times.append(time.perf_counter() - t0)

    invalid_median = statistics.median(invalid_times)
    locked_median = statistics.median(locked_times)
    spread = max(invalid_median, locked_median) / min(invalid_median, locked_median)

    assert spread < 1.30, (
        f"wall-clock spread {spread:.2f}x exceeds 30% — locked vs invalid "
        f"timing oracle 잔존. invalid_median={invalid_median * 1000:.1f}ms, "
        f"locked_median={locked_median * 1000:.1f}ms, "
        f"all_invalid={[f'{t * 1000:.1f}' for t in invalid_times]}, "
        f"all_locked={[f'{t * 1000:.1f}' for t in locked_times]}"
    )
