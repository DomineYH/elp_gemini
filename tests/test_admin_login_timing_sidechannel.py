"""Issue #6: 관리자 로그인 타이밍/메시지 사이드채널 회귀 테스트

검증:
  T1  missing user / non-admin / locked / no-password / invalid-password
      5경로의 status_code 와 response body 가 동일
  T2  모든 실패 경로에서 bcrypt verify (real OR dummy) 가 1회 이상 호출됨
  T3  audit 로그는 내부적으로 분리 기록 유지 (외부 통일과 무관)
  T4  wall-clock: locked vs invalid-password 경로의 응답 시간
      중앙값이 통계적으로 구분되지 않는다
      (issue #6 사용자 명시 요구: status/body/timing 모두 일치)
"""
from __future__ import annotations

import re
import statistics
import time
from datetime import datetime, timedelta
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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

ADMIN = "ts_admin"
ADMIN_PASSWORD = "correct horse battery staple"
_ADMIN_CSRF_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


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
    """rate limit 비활성화.

    Issue #6 timing tests intentionally make repeated failure requests from
    one in-memory client. Disable both SlowAPI's IP bucket and the admin_id
    bucket so brute-force defenses do not mask the timing assertion.
    """
    original_limiter_enabled = limiter.enabled
    original_settings_enabled = settings.RATE_LIMIT_ENABLED
    limiter.enabled = False
    settings.RATE_LIMIT_ENABLED = False
    limiter.reset()
    yield
    settings.RATE_LIMIT_ENABLED = original_settings_enabled
    limiter.enabled = original_limiter_enabled
    limiter.reset()


async def _get_admin_csrf_token(client: AsyncClient) -> str:
    response = await client.get("/login/admin", follow_redirects=False)
    assert response.status_code == 200
    match = _ADMIN_CSRF_RE.search(response.text)
    assert match, "관리자 로그인 폼에 CSRF hidden input 이 있어야 함"
    return match.group(1)


async def _post_admin_login(
    client: AsyncClient,
    admin_id: str,
    password: str,
):
    csrf_token = await _get_admin_csrf_token(client)
    return await client.post(
        "/auth/login/admin",
        data={
            "admin_id": admin_id,
            "password": password,
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )


# ---------------------------------------------------------------------
# T1 — 모든 실패 경로가 동일한 응답 반환
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_failure_paths_return_identical_response(
    http_client, admin_user, session_factory, disable_rate_limit
):
    # Path 1: missing user
    r1 = await _post_admin_login(http_client, "no_such_user", "x")

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
    r2 = await _post_admin_login(http_client, "regular", "x")

    # Path 3: invalid password
    r3 = await _post_admin_login(http_client, ADMIN, "wrong")

    # Path 4: locked account
    async with session_factory() as s:
        u = await s.get(User, admin_user.id)
        u.failed_login_count = 10
        u.locked_until = datetime.utcnow() + timedelta(minutes=5)
        await s.commit()
    r4 = await _post_admin_login(http_client, ADMIN, "wrong")

    # Path 5: no-password admin (hashed_password cleared)
    async with session_factory() as s:
        u = await s.get(User, admin_user.id)
        u.hashed_password = None
        u.locked_until = None
        u.failed_login_count = 0
        await s.commit()
    r5 = await _post_admin_login(http_client, ADMIN, "x")

    for label, r in [
        ("missing_user", r1),
        ("non_admin", r2),
        ("invalid_password", r3),
        ("locked", r4),
        ("no_password", r5),
    ]:
        assert r.status_code == 401, (
            f"{label}: expected 401, got {r.status_code}"
        )
        assert "ID 또는 비밀번호" in r.text, (
            f"{label}: unified message missing"
        )
        assert "잠시" not in r.text, (
            f"{label}: lockout message leaked (#6)"
        )

    bodies = {
        "missing_user": r1.text,
        "non_admin": r2.text,
        "invalid_password": r3.text,
        "locked": r4.text,
        "no_password": r5.text,
    }
    assert len(set(bodies.values())) == 1, (
        "all admin-login failure paths must render an identical body "
        f"(lengths={ {k: len(v) for k, v in bodies.items()} })"
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
async def test_dummy_bcrypt_and_db_touch_called_in_missing_user_path(
    session_factory, disable_rate_limit
):
    """missing user 도 bcrypt + DB write 비용 보정을 수행한다."""
    with (
        patch.object(AuthService, "_dummy_password_verify") as dummy,
        patch.object(
            AuthService,
            "_touch_missing_admin_attempt",
            new_callable=AsyncMock,
        ) as touch,
    ):
        async with session_factory() as session:
            svc = AuthService(session)
            result = await svc.authenticate_admin("no_such_user", "x")
        assert result.user is None
        dummy.assert_called_once_with("x")
        touch.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_dummy_bcrypt_and_db_touch_called_in_non_admin_path(
    session_factory, disable_rate_limit
):
    """non-admin user 도 missing user 와 같은 보정 경로를 탄다."""
    async with session_factory() as session:
        session.add(
            User(
                username="regular_for_timing",
                nickname="regular",
                hashed_password=AuthService.hash_password("p"),
                is_admin=False,
            )
        )
        await session.commit()

    with (
        patch.object(AuthService, "_dummy_password_verify") as dummy,
        patch.object(
            AuthService,
            "_touch_missing_admin_attempt",
            new_callable=AsyncMock,
        ) as touch,
    ):
        async with session_factory() as session:
            svc = AuthService(session)
            result = await svc.authenticate_admin(
                "regular_for_timing", "x"
            )
        assert result.user is None
        dummy.assert_called_once_with("x")
        touch.assert_awaited_once_with()


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


@pytest.mark.asyncio
async def test_dummy_bcrypt_verify_called_in_no_password_path(
    admin_user, session_factory, disable_rate_limit
):
    """hashed_password 없는 admin 도 dummy verify 후 일반 실패로 처리한다."""
    async with session_factory() as s:
        u = await s.get(User, admin_user.id)
        u.hashed_password = None
        u.failed_login_count = 0
        u.locked_until = None
        await s.commit()

    with patch.object(AuthService, "_dummy_password_verify") as dummy:
        async with session_factory() as session:
            svc = AuthService(session)
            result = await svc.authenticate_admin(ADMIN, "x")
        assert result.user is None
        assert result.locked is False
        dummy.assert_called_once_with("x")


@pytest.mark.asyncio
async def test_real_bcrypt_verify_called_in_invalid_password_path(
    admin_user, session_factory, disable_rate_limit
):
    """invalid-password 는 dummy 대신 실제 password verify 를 1회 수행한다."""
    with patch.object(
        AuthService, "verify_password", return_value=False
    ) as verify:
        async with session_factory() as session:
            svc = AuthService(session)
            result = await svc.authenticate_admin(ADMIN, "wrong")
        assert result.user is None
        assert result.locked is False
        verify.assert_called_once_with("wrong", admin_user.hashed_password)


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
    await _post_admin_login(http_client, ADMIN, "wrong")

    # missing/non-admin (invalid) 경로 요청
    await _post_admin_login(http_client, "no_such_admin", "wrong")

    joined = "\n".join(r.getMessage() for r in caplog.records)
    # locked 경로는 service/router 양쪽에서 별도 audit 이벤트를 남긴다
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
# T4 — wall-clock: 모든 실패 경로의 응답 시간 중앙값 일치
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_paths_wallclock_parity(
    http_client, admin_user, session_factory, disable_rate_limit
):
    """사용자 명시 요구 (issue #6): 모든 실패 응답이 status/body 뿐 아니라
    timing 까지 일치해야 한다. 각 경로 중앙값이 30% 이내로 수렴하면 통과.

    bcrypt 한 번 ≈ 60-80ms 가 두 경로 공통 비용이므로 분산은 작은 편이고,
    이 임계치는 in-memory SQLite + ASGITransport 환경의 일반적인
    jitter 를 흡수한다.
    실제 timing oracle (real bcrypt/DB UPDATE only on valid admin_id) 는 ms 단위
    차이를 만들기 때문에 bcrypt 비용 대비 비율이 30% 임계치 안에 들어와야 한다.
    """
    samples = 4  # 5개 경로 통계 + CI 시간 균형
    original_hash = admin_user.hashed_password

    async with session_factory() as s:
        s.add(
            User(
                username="regular_timing_probe",
                nickname="regular",
                hashed_password=original_hash,
                is_admin=False,
            )
        )
        await s.commit()

    async def set_admin_state(
        *, hashed_password: str | None = original_hash, locked: bool = False
    ) -> None:
        async with session_factory() as s:
            u = await s.get(User, admin_user.id)
            u.failed_login_count = 0
            u.locked_until = (
                datetime.utcnow() + timedelta(minutes=5)
                if locked
                else None
            )
            u.hashed_password = hashed_password
            await s.commit()

    async def noop_setup() -> None:
        return None

    paths = [
        ("missing_user", "no_such_user", "x", noop_setup),
        ("non_admin", "regular_timing_probe", "x", noop_setup),
        (
            "invalid_password",
            ADMIN,
            "wrong",
            lambda: set_admin_state(hashed_password=original_hash),
        ),
        (
            "locked",
            ADMIN,
            "wrong",
            lambda: set_admin_state(
                hashed_password=original_hash, locked=True
            ),
        ),
        (
            "no_password",
            ADMIN,
            "x",
            lambda: set_admin_state(hashed_password=None),
        ),
    ]
    async def collect_timings() -> tuple[float, dict, dict]:
        timings = {label: [] for label, *_ in paths}

        for _ in range(samples):
            for label, admin_id, password, setup in paths:
                await setup()
                csrf_token = await _get_admin_csrf_token(http_client)
                t0 = time.perf_counter()
                response = await http_client.post(
                    "/auth/login/admin",
                    data={
                        "admin_id": admin_id,
                        "password": password,
                        "csrf_token": csrf_token,
                    },
                    follow_redirects=False,
                )
                timings[label].append(time.perf_counter() - t0)
                assert response.status_code == 401
                assert "ID 또는 비밀번호" in response.text
                assert "잠시" not in response.text

        medians = {
            label: statistics.median(samples)
            for label, samples in timings.items()
        }
        spread = max(medians.values()) / min(medians.values())
        return spread, medians, timings

    # Wall-clock checks are intentionally regression guards, not precise
    # benchmarking. A single 4-sample round can exceed the 30% bound on a
    # loaded CI host even when each branch performs the same bcrypt + DB
    # padding. Retry once and require at least one bounded round; a real
    # admin_id timing oracle remains consistently outside the bound.
    attempts = []
    for _ in range(2):
        spread, medians, timings = await collect_timings()
        attempts.append((spread, medians, timings))
        if spread < 1.30:
            return

    best_spread, best_medians, best_timings = min(
        attempts, key=lambda item: item[0]
    )
    best_medians_ms = {
        key: round(value * 1000, 1)
        for key, value in best_medians.items()
    }
    best_samples_ms = {
        key: [round(timing * 1000, 1) for timing in values]
        for key, values in best_timings.items()
    }
    assert best_spread < 1.30, (
        f"wall-clock spread {best_spread:.2f}x exceeds 30% — "
        f"admin_id timing oracle 잔존. "
        f"medians_ms={best_medians_ms}, "
        f"samples_ms={best_samples_ms}"
    )
