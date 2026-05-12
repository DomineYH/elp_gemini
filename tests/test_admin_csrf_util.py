"""admin_csrf 유틸 단위 테스트."""
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.utils.admin_csrf import (
    ADMIN_CSRF_HEADER,
    ensure_admin_csrf_token,
    require_admin_csrf_token,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")

    @app.get("/get-token")
    def get_token(request: Request):
        token = ensure_admin_csrf_token(request)
        return {"token": token}

    @app.post("/protected")
    def protected(request: Request):
        require_admin_csrf_token(request)
        return {"ok": True}

    return app


def test_ensure_and_require_round_trip():
    client = TestClient(_build_app())

    r = client.get("/get-token")
    assert r.status_code == 200
    token = r.json()["token"]
    assert token

    # Missing header → 403
    r = client.post("/protected")
    assert r.status_code == 403

    # Matching header → 200
    r = client.post("/protected", headers={ADMIN_CSRF_HEADER: token})
    assert r.status_code == 200

    # Wrong header → 403
    r = client.post("/protected", headers={ADMIN_CSRF_HEADER: "bogus"})
    assert r.status_code == 403


def test_ensure_returns_same_token_within_session():
    client = TestClient(_build_app())
    first = client.get("/get-token").json()["token"]
    second = client.get("/get-token").json()["token"]
    assert first == second
