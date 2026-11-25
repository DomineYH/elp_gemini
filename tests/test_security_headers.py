"""#268 items 2, 3: 보안 응답 헤더와 favicon. #440: Cache-Control no-store."""

import base64
import io
import json
import zipfile
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
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
from app.middleware.security_headers import (
    CONTENT_SECURITY_POLICY,
    SecurityHeadersMiddleware,
)
from app.models.analysis_reports import AnalysisReport
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_session import SimulationSession
from app.models.users import User
from app.routers import views as views_mod

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


# ===== #440: 정적 파일 밖 모든 응답에 Cache-Control: no-store =====

HTML = {"accept": "text/html"}
COOKIE = settings.SESSION_COOKIE_NAME


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
async def seeded(tmp_path, monkeypatch):
    """임시 DB에 사용자·관리자, 업로드 PDF, 보고서, 종료된 시뮬레이션을 만든다"""
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
    report_path = tmp_path / "r.md"
    report_path.write_text("# 보고서 440\n", encoding="utf-8")
    async with factory() as db:
        user = User(username="u440", nickname="u440", hashed_password="x")
        admin = User(
            username="a440", nickname="a440", hashed_password="x", is_admin=True
        )
        db.add_all([user, admin])
        await db.flush()
        upload = LessonPlanUpload(
            user_id=user.id,
            filename="a.pdf",
            original_filename="a.pdf",
            file_hash="a" * 64,
        )
        db.add(upload)
        await db.flush()
        report = AnalysisReport(
            user_id=user.id,
            lessonplan_filename="a.pdf",
            lessonplan_original_name="a.pdf",
            report_filename="r.md",
            report_path=str(report_path),
            upload_id=upload.id,
        )
        sim = SimulationSession(
            user_id=user.id,
            upload_id=upload.id,
            persona_count=1,
            model_name="x",
            status="finished",
        )
        db.add_all([report, sim])
        await db.commit()

    owner_dir = tmp_path / "uploads" / str(user.id)
    owner_dir.mkdir(parents=True)
    (owner_dir / "a.pdf").write_bytes(b"%PDF-1.4 test440\n%%EOF\n")
    real_path_cls = views_mod.Path

    def _patched_path(*args, **kwargs):
        p = real_path_cls(*args, **kwargs)
        if str(p) == "app/static/uploads":
            return real_path_cls(str(tmp_path / "uploads"))
        return p

    monkeypatch.setattr(views_mod, "Path", _patched_path)
    # HTML 경로의 미들웨어 DB 검증도 같은 테스트 DB를 보게 한다
    monkeypatch.setattr(
        "app.middleware.auth_middleware.async_session_maker", factory
    )

    async def _get_db_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    clients = []

    def _client(who=None) -> AsyncClient:
        c = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        if who is not None:
            c.cookies.set(COOKIE, _cookie(who))
        clients.append(c)
        return c

    yield {
        "client": _client,
        "user": user,
        "admin": admin,
        "report_id": report.id,
        "sid": sim.id,
    }
    for c in clients:
        await c.aclose()
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


def _assert_no_store(response, status=200):
    assert response.status_code == status, response.text[:200]
    assert response.headers.get_list("cache-control") == ["no-store"]


@pytest.mark.asyncio
async def test_private_pages_and_apis_no_store(seeded):
    user = seeded["client"](seeded["user"])
    admin = seeded["client"](seeded["admin"])
    rid, sid = seeded["report_id"], seeded["sid"]
    cases = [
        (user, "/dashboard", HTML),
        (user, f"/reports/view/{rid}", HTML),
        (user, "/simulation/setup", HTML),
        (user, f"/simulation/sessions/{sid}", HTML),
        (user, "/api/lessonplan/reports", {}),
        (user, "/api/qna/sessions", {}),
        (admin, "/admin/dashboard", HTML),
        (admin, "/admin/users", HTML),
        (admin, f"/admin/reports/view/{rid}", HTML),
        (admin, "/admin/api/users/stats", {}),
    ]
    for client, path, headers in cases:
        response = await client.get(path, headers=headers)
        _assert_no_store(response)
        _assert_security_headers(response)


@pytest.mark.asyncio
async def test_auth_cache_control(seeded):
    anon = seeded["client"]()

    redirect = await anon.get("/dashboard", headers=HTML)
    _assert_no_store(redirect, 302)
    assert redirect.headers["location"] == "/login"
    for path in ("/login", "/login/admin"):
        _assert_no_store(await anon.get(path, headers=HTML))
    user = seeded["client"](seeded["user"])
    with patch("app.services.file_search_service.FileSearchService") as fss:
        fss.return_value.delete_store_by_display_name = AsyncMock()
        _assert_no_store(await user.post("/auth/logout", headers=HTML), 302)


@pytest.mark.asyncio
async def test_personal_downloads_no_store(seeded):
    user = seeded["client"](seeded["user"])
    admin = seeded["client"](seeded["admin"])

    pdf = await user.get("/dashboard/uploads/a.pdf")
    _assert_no_store(pdf)
    assert pdf.content == b"%PDF-1.4 test440\n%%EOF\n"
    report = await user.get(
        f"/api/lessonplan/reports/{seeded['report_id']}/download"
    )
    _assert_no_store(report)
    assert report.text == "# 보고서 440\n"
    export = await admin.get("/admin/api/exports/all.zip")
    _assert_no_store(export)
    assert zipfile.ZipFile(io.BytesIO(export.content)).namelist()


@pytest.mark.parametrize(
    "path, revalidated",
    [
        ("/static/css/tailwind.css", 304),
        ("/static/js/safe_markdown.js", 304),
        # favicon 은 일반 FileResponse 라 조건부 요청에도 200 (#440 범위 밖)
        ("/favicon.ico", 200),
    ],
)
def test_static_cache_revalidation(path, revalidated):
    client = TestClient(app)

    first = client.get(path)
    second = client.get(path, headers={"if-none-match": first.headers["etag"]})

    assert first.status_code == 200
    assert "cache-control" not in first.headers
    assert second.status_code == revalidated
    assert "cache-control" not in second.headers


@pytest.mark.parametrize("path", ["/staticx/x", "/favicon.ico/extra"])
def test_cache_path_boundaries(path):
    response = TestClient(app).get(path)

    _assert_no_store(response, 404)


def test_explicit_cache_control_preserved():
    async def inner(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"private")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    response = TestClient(SecurityHeadersMiddleware(inner)).get("/x")

    assert response.headers.get_list("cache-control") == ["private"]


def test_error_cache_control(error_routes):
    client = TestClient(app, raise_server_exceptions=False)

    _assert_no_store(client.get("/__test_404", headers=HTML), 404)
    for path in ("/__test_500", "/api/__test_500"):
        response = client.get(path, headers=HTML)
        assert response.status_code == 500
        _assert_security_headers(response)
        # 미처리 500 은 미들웨어 바깥에서 나가 핸들러가 no-store 를 직접 붙인다 (#440)
        assert response.headers.get_list("cache-control") == ["no-store"]


def test_logged_in_error_page_no_store(seeded, error_routes):
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set(COOKIE, _cookie(seeded["user"]))

    response = client.get("/__test_500", headers=HTML)

    assert response.status_code == 500
    assert f"{seeded['user'].nickname}님" in response.text
    _assert_security_headers(response)
    assert response.headers.get_list("cache-control") == ["no-store"]
