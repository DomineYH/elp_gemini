"""#444: 브라우저 요청의 라우팅 404·405와 검증 422는 error.html, 그 밖은 JSON 그대로."""

import base64
import json

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.middleware import AuthMiddleware
from app.middleware.security_headers import SECURITY_HEADERS
from app.models.users import User

HTML = {"accept": "text/html"}
NOT_FOUND = b'{"detail":"Not Found"}'
NOT_ALLOWED = b'{"detail":"Method Not Allowed"}'


def _int_error(loc_name: str) -> bytes:
    return (
        b'{"detail":[{"type":"int_parsing","loc":["path","'
        + loc_name.encode()
        + b'"],"msg":"Input should be a valid integer, unable to parse '
        b'string as an integer","input":"abc"}]}'
    )


REGISTER_EMPTY = (
    b'{"detail":['
    + b",".join(
        b'{"type":"missing","loc":["body","'
        + name
        + b'"],"msg":"Field required","input":null}'
        for name in (b"user_id", b"password", b"password_confirm")
    )
    + b"]}"
)

# (누가, 메서드, 경로, 지금의 상태, 지금의 JSON 바이트)
ROUTING = [
    ("user", "GET", "/no-such-page", 404, NOT_FOUND),
    ("user", "GET", "/reports/abc", 404, NOT_FOUND),
    ("user", "GET", "/static/js/nope.js", 404, NOT_FOUND),
    (None, "GET", "/auth/logout", 405, NOT_ALLOWED),
]
VALIDATION = [
    ("user", "GET", "/reports/view/abc", 422, _int_error("report_id")),
    ("user", "GET", "/simulation/sessions/abc", 422, _int_error("sid")),
    ("admin", "GET", "/admin/users/abc", 422, _int_error("user_id")),
    (None, "POST", "/auth/register", 422, REGISTER_EMPTY),
]


def _cookie(user: User) -> str:
    """SessionMiddleware 와 같은 방식으로 서명한 세션 쿠키 값"""
    data = {
        "user_id": user.id,
        "is_admin": user.is_admin,
        "username": user.username,
        "nickname": user.nickname,
        "session_version": user.session_version or 0,
    }
    raw = base64.b64encode(json.dumps(data).encode())
    return TimestampSigner(str(settings.SECRET_KEY)).sign(raw).decode()


@pytest_asyncio.fixture
async def clients(monkeypatch):
    """같은 임시 DB를 보는 비로그인·사용자·관리자 TestClient"""
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
    async with factory() as db:
        user = User(username="u444", nickname="u444", hashed_password="x")
        admin = User(
            username="a444", nickname="a444", hashed_password="x", is_admin=True
        )
        db.add_all([user, admin])
        await db.commit()
    # HTML 경로의 미들웨어 DB 검증도 같은 테스트 DB를 보게 한다
    monkeypatch.setattr(
        "app.middleware.auth_middleware.async_session_maker", factory
    )

    async def _get_db_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    result = {}
    for who, account in (("user", user), ("admin", admin), (None, None)):
        client = TestClient(app, follow_redirects=False)
        if account is not None:
            client.cookies.set(settings.SESSION_COOKIE_NAME, _cookie(account))
        result[who] = client
    yield result
    for client in result.values():
        client.close()
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


def _assert_security_headers(response):
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, name


def _assert_error_page(response, status, detail):
    assert response.status_code == status
    assert response.headers["content-type"].startswith("text/html")
    assert response.template.name == "error.html"
    assert detail in response.text
    assert "홈으로 돌아가기" in response.text
    _assert_security_headers(response)


@pytest.mark.parametrize("who, method, path, status, _", ROUTING)
def test_html_routing_errors(clients, who, method, path, status, _):
    response = clients[who].request(method, path, headers=HTML)

    detail = (
        "페이지를 찾을 수 없습니다." if status == 404 else "잘못된 접근입니다."
    )
    _assert_error_page(response, status, detail)
    if status == 405:
        assert response.headers["allow"] == "POST"


@pytest.mark.parametrize("who, method, path, status, _", VALIDATION)
def test_html_validation_errors(clients, who, method, path, status, _):
    response = clients[who].request(method, path, headers=HTML)

    _assert_error_page(
        response, status, "주소 또는 입력값이 올바르지 않습니다."
    )
    assert '"loc"' not in response.text
    assert '"msg"' not in response.text


@pytest.mark.parametrize("accept", ["*/*", None, "application/json"])
@pytest.mark.parametrize(
    "who, method, path, status, body", ROUTING + VALIDATION
)
def test_error_json_bytes(clients, accept, who, method, path, status, body):
    client = clients[who]
    request = client.build_request(method, path)
    if accept is None:
        del request.headers["accept"]
    else:
        request.headers["accept"] = accept

    response = client.send(request)

    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    assert response.content == body
    _assert_security_headers(response)


@pytest.mark.parametrize(
    "path, status, body",
    [
        ("/api/no-such", 404, NOT_FOUND),
        ("/api/lessonplan/reports/abc", 422, _int_error("report_id")),
    ],
)
def test_api_html_accept_stays_json(clients, path, status, body):
    response = clients["user"].get(path, headers=HTML)

    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    assert response.content == body
    _assert_security_headers(response)


def test_report_404_keeps_detail(clients):
    response = clients["user"].get("/reports/view/999999", headers=HTML)

    _assert_error_page(response, 404, "보고서를 찾을 수 없습니다.")


def test_anonymous_html_redirect(clients):
    response = clients[None].get("/no-such-page", headers=HTML)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    _assert_security_headers(response)


@pytest.fixture
def unauthorized_routes(monkeypatch):
    """FastAPI HTTPException 401 을 던지는 임시 공개 라우트"""

    async def unauthorized():
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    paths = ["/__t401", "/api/__t401", "/admin/__t401"]
    for path in paths:
        app.add_api_route(path, unauthorized)
    monkeypatch.setattr(
        AuthMiddleware,
        "WHITELIST_PATHS",
        AuthMiddleware.WHITELIST_PATHS + paths,
    )
    yield
    del app.router.routes[-len(paths) :]


@pytest.mark.parametrize(
    "path, login",
    [
        ("/__t401", "/login"),
        ("/api/__t401", "/login"),
        ("/admin/__t401", "/login/admin"),
    ],
)
def test_route_401_redirect(clients, unauthorized_routes, path, login):
    client = clients[None]

    html = client.get(path, headers=HTML)
    other = client.get(path)

    assert html.status_code == 302
    assert html.headers["location"] == login
    _assert_security_headers(html)
    assert other.status_code == 401
    assert other.json() == {"detail": "로그인이 필요합니다."}
    _assert_security_headers(other)
