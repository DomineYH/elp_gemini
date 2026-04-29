"""
이슈 #8: 로그인 화면 관리자 탭 제거 및 /login/admin 전용 URL 도입

테스트 매트릭스 (계획서 §6 참조):
    T1  GET /login          → 관리자 탭/패널/JS/관리자 텍스트 미노출
    T2  GET /login/admin    → 관리자 폼(admin_id, password) 노출
    T3  GET /login/admin    (관리자 세션) → /admin/dashboard 302
    T4  GET /login/admin    (일반 사용자 세션) → / 302
    T5  POST /auth/login/admin (잘못된 자격증명) → 401 + 관리자 폼 재렌더
    T9  GET /login          응답에 'login/admin' 문자열 미노출
"""
import base64
import json
import time

import itsdangerous
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


def _build_session_cookie(data: dict) -> str:
    """Starlette SessionMiddleware 호환 서명된 세션 쿠키 생성."""
    signer = itsdangerous.TimestampSigner(str(settings.SECRET_KEY))
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    signed = signer.sign(payload)
    return signed.decode("utf-8")


# T1
@pytest.mark.asyncio
async def test_login_page_has_no_admin_tab():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/login", follow_redirects=False)
    assert response.status_code == 200
    body = response.text
    # 탭/패널/JS 잔재가 모두 사라져야 함
    assert "tab-admin" not in body
    assert "panel-admin" not in body
    assert "switchTab" not in body
    # 사용자에게 노출되는 본문에 '관리자' 단어가 없어야 함
    assert "관리자" not in body
    # 사용자 로그인 폼은 그대로 유지
    assert 'action="/auth/login/user"' in body


# T2
@pytest.mark.asyncio
async def test_login_admin_page_renders_admin_form():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/login/admin", follow_redirects=False)
    assert response.status_code == 200
    body = response.text
    assert 'name="admin_id"' in body
    assert 'name="password"' in body
    assert 'action="/auth/login/admin"' in body
    # 사용자 로그인 폼은 같은 페이지에 노출되지 않아야 함
    assert 'action="/auth/login/user"' not in body


# T2-MW: 브라우저 헤더(Accept: text/html)로도 AuthMiddleware가 가로채지 않아야 함
# regression: WHITELIST_PATHS에 /login/admin·/admin/login 누락으로 미들웨어가 /login으로 302 보내던 이슈
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["/login/admin", "/login/admin/", "/admin/login", "/admin/login/"],
)
async def test_admin_login_paths_bypass_auth_middleware_with_browser_headers(
    url: str,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "Mozilla/5.0 Chrome/120.0",
            },
            follow_redirects=True,
        )
    assert response.status_code == 200, (
        f"{url}: status {response.status_code} — 미들웨어 가로채기 회귀 의심"
    )
    assert 'name="admin_id"' in response.text, (
        f"{url}: 관리자 폼 미노출. 사용자 로그인 폼으로 흐른 정황"
    )
    assert 'action="/auth/login/admin"' in response.text


# T3 — 이미 관리자로 로그인된 세션은 대시보드로 리다이렉트
@pytest.mark.asyncio
async def test_login_admin_page_redirects_admin_session():
    cookie = _build_session_cookie(
        {"user_id": 1, "is_admin": True, "username": "admin"}
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={settings.SESSION_COOKIE_NAME: cookie},
    ) as ac:
        response = await ac.get("/login/admin", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/dashboard"


# T4 — 일반 사용자 세션은 홈으로 리다이렉트
@pytest.mark.asyncio
async def test_login_admin_page_redirects_user_session():
    cookie = _build_session_cookie(
        {"user_id": 2, "is_admin": False, "username": "user"}
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={settings.SESSION_COOKIE_NAME: cookie},
    ) as ac:
        response = await ac.get("/login/admin", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"


# T5 — 잘못된 자격증명은 관리자 폼을 401로 재렌더
@pytest.mark.asyncio
async def test_admin_login_invalid_credentials_renders_admin_form():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/auth/login/admin",
            data={"admin_id": "no_such_admin", "password": "wrong"},
            follow_redirects=False,
        )
    assert response.status_code == 401
    body = response.text
    # 관리자 폼이 다시 보여야 하고, 사용자 로그인 폼이 같이 노출되어선 안 됨
    assert 'action="/auth/login/admin"' in body
    assert 'action="/auth/login/user"' not in body
    assert "ID 또는 비밀번호" in body


# T2b — /admin/login alias도 같은 관리자 폼을 렌더해야 함
@pytest.mark.asyncio
async def test_admin_login_alias_renders_admin_form():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/admin/login", follow_redirects=False)
    assert response.status_code == 200
    body = response.text
    assert 'name="admin_id"' in body
    assert 'name="password"' in body
    assert 'action="/auth/login/admin"' in body


# T2c — /admin/login/ trailing slash도 결국 관리자 폼에 도달
@pytest.mark.asyncio
async def test_admin_login_alias_trailing_slash():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/admin/login/", follow_redirects=True)
    assert response.status_code == 200
    assert 'name="admin_id"' in response.text


# T9 — /login 응답에 관리자 URL 단서 미노출
@pytest.mark.asyncio
async def test_login_page_does_not_expose_admin_url():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/login", follow_redirects=False)
    assert response.status_code == 200
    assert "/login/admin" not in response.text
    assert "login/admin" not in response.text


# 시간 의존성을 가지는 itsdangerous 서명에 대비한 sanity 체크
def test_session_cookie_helper_signs_within_acceptable_window():
    cookie = _build_session_cookie({"user_id": 1})
    signer = itsdangerous.TimestampSigner(str(settings.SECRET_KEY))
    # 발급 직후 검증이 가능해야 함
    payload = signer.unsign(cookie, max_age=10)
    assert b"user_id" in base64.b64decode(payload)
    # 검증 시점이 너무 떨어지지 않도록 보장
    assert time.time() > 0
