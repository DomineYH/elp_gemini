"""#268 items 2, 3: 보안 응답 헤더와 favicon."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.middleware import AuthMiddleware
from app.middleware.security_headers import CONTENT_SECURITY_POLICY

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
    "referrer-policy": "strict-origin-when-cross-origin",
    "content-security-policy-report-only": CONTENT_SECURITY_POLICY,
}


def _assert_security_headers(response):
    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, name
    assert "strict-transport-security" not in response.headers


@pytest.mark.parametrize(
    "path, status, content_type",
    [
        ("/login", 200, "text/html"),
        ("/static/js/safe_markdown.js", 200, "text/javascript"),
        ("/static/css/tailwind.css", 200, "text/css"),
        ("/favicon.ico", 200, "image/svg+xml"),
        ("/api/nope", 404, "application/json"),
    ],
)
def test_security_headers_on_every_response(path, status, content_type):
    response = TestClient(app).get(path, follow_redirects=False)

    assert response.status_code == status
    assert response.headers["content-type"].startswith(content_type)
    _assert_security_headers(response)


@pytest.mark.parametrize("path", ["/dashboard", "/admin/users", "/auth/me"])
def test_security_headers_on_auth_redirects(path):
    response = TestClient(app).get(
        path, headers={"accept": "text/html"}, follow_redirects=False
    )

    assert response.status_code == 302
    _assert_security_headers(response)


@pytest.fixture
def error_routes(monkeypatch):
    """HTML 404 / 500 을 내는 임시 공개 라우트"""

    async def not_found():
        raise HTTPException(status_code=404, detail="없음")

    async def boom():
        raise RuntimeError("boom")

    routes = {
        "/__test_404": not_found,
        "/__test_500": boom,
        "/api/__test_500": boom,
    }
    for path, endpoint in routes.items():
        app.add_api_route(path, endpoint)
    monkeypatch.setattr(
        AuthMiddleware,
        "WHITELIST_PATHS",
        AuthMiddleware.WHITELIST_PATHS + list(routes),
    )
    yield
    del app.router.routes[-len(routes) :]


@pytest.mark.parametrize(
    "path, status, content_type",
    [
        ("/__test_404", 404, "text/html"),
        ("/__test_500", 500, "text/html"),
        ("/api/__test_500", 500, "application/json"),
    ],
)
def test_security_headers_on_error_responses(
    error_routes, path, status, content_type
):
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(path, headers={"accept": "text/html"})

    assert response.status_code == status
    assert response.headers["content-type"].startswith(content_type)
    _assert_security_headers(response)


def test_csp_allows_marked_cdn_and_drops_tailwind_cdn():
    assert "https://cdn.jsdelivr.net" in CONTENT_SECURITY_POLICY
    assert "cdn.tailwindcss.com" not in CONTENT_SECURITY_POLICY
    assert "worker-src 'self' blob:" in CONTENT_SECURITY_POLICY


def test_base_template_links_favicon():
    with open("app/templates/base.html", encoding="utf-8") as f:
        assert '<link rel="icon" href="/favicon.ico"' in f.read()
