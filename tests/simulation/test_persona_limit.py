"""관리자가 정하는 시뮬레이션 학생 페르소나 최대 수 (#255)."""

import re

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.app_state import AppState
from app.models.simulation_session import SimulationSession
from app.utils.admin_csrf import ADMIN_CSRF_HEADER

from .conftest import run
from .test_session_create_enter import _explicit_body, _phases

PAGE = "/admin/simulation/settings"
API = "/admin/api/simulation/persona-limit"


def _token(client):
    html = client.get(PAGE).text
    m = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert m, "csrf-token meta missing"
    return m.group(1)


@pytest.fixture
def admin_client(client, as_user, admin):
    as_user(admin)
    client.headers[ADMIN_CSRF_HEADER] = _token(client)
    return client


@pytest.fixture
def limit_3(admin_client, as_user, teacher):
    assert admin_client.put(API, json={"max_personas": 3}).status_code == 200
    as_user(teacher)
    return admin_client


def _random_body(n):
    return {
        "random": {"n": n, "grade": "all", "level": "all", "seed": 1},
        "phases": _phases(),
    }


def _sessions(sim_db):
    async def _go():
        async with sim_db() as db:
            return await db.scalar(select(func.count(SimulationSession.id)))

    return run(_go())


def _put_state(sim_db, value):
    async def _go():
        async with sim_db() as db:
            db.add(AppState(key="sim_max_personas", value=value))
            await db.commit()

    run(_go())


def test_get_default_when_unset(admin_client):
    r = admin_client.get(API)
    assert r.status_code == 200
    assert r.json() == {
        "max_personas": 4,
        "min": 2,
        "absolute_max": settings.SIM_MAX_PERSONAS,
        "configured": False,
    }


def test_put_saves_and_get_reads_back(admin_client, sim_db, monkeypatch):
    # get_db는 응답 뒤에 커밋하므로, 라우트가 직접 커밋해야만 남는다
    async def _no_commit_db():
        async with sim_db() as session:
            yield session
            await session.rollback()

    monkeypatch.setitem(app.dependency_overrides, get_db, _no_commit_db)
    r = admin_client.put(API, json={"max_personas": 3})
    assert r.status_code == 200
    assert r.json()["max_personas"] == 3
    got = admin_client.get(API).json()
    assert got["max_personas"] == 3
    assert got["configured"] is True


@pytest.mark.parametrize("value", [1, 7, "abc"])
def test_put_out_of_range_is_422(admin_client, value):
    r = admin_client.put(API, json={"max_personas": value})
    assert r.status_code == 422
    assert admin_client.get(API).json()["configured"] is False


def test_non_admin_is_refused(client):
    assert client.get(API).status_code == 403
    assert client.put(API, json={"max_personas": 3}).status_code == 403


def test_put_without_csrf_is_403(admin_client):
    del admin_client.headers[ADMIN_CSRF_HEADER]
    assert admin_client.put(API, json={"max_personas": 3}).status_code == 403
    admin_client.headers[ADMIN_CSRF_HEADER] = "wrong"
    assert admin_client.put(API, json={"max_personas": 3}).status_code == 403
    assert admin_client.get(API).json()["max_personas"] == 4


def test_unauthenticated_is_refused(client):
    app.dependency_overrides.pop(get_current_user)
    assert client.get(API).status_code == 401
    assert client.put(API, json={"max_personas": 3}).status_code == 401


def test_setup_page_uses_admin_limit(limit_3, teacher, make_upload):
    make_upload(teacher)
    html = limit_3.get("/simulation/setup").text
    assert 'max="3" value="3"' in html
    assert "최대 3명(관리자 설정)" in html
    assert f'n: "{settings.SIM_MAX_PERSONAS}"' in html


def test_create_session_over_limit_is_422(
    limit_3, sim_db, teacher, make_upload, fake_gemini
):
    make_upload(teacher)
    r = limit_3.post("/api/simulation/sessions", json=_random_body(4))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "TOO_MANY_PERSONAS"
    r = limit_3.post("/api/simulation/sessions", json=_explicit_body(limit_3))
    assert r.status_code == 422
    assert _sessions(sim_db) == 0
    r = limit_3.post("/api/simulation/sessions", json=_random_body(3))
    assert r.status_code == 201


@pytest.mark.parametrize("value", ["abc", "9", "1"])
def test_bad_app_state_value_falls_back(
    admin_client, as_user, teacher, sim_db, make_upload, fake_gemini, value
):
    _put_state(sim_db, value)
    got = admin_client.get(API).json()
    assert got["max_personas"] == 4
    assert got["configured"] is False
    as_user(teacher)
    make_upload(teacher)
    r = admin_client.post("/api/simulation/sessions", json=_random_body(4))
    assert r.status_code == 201
    r = admin_client.post("/api/simulation/sessions", json=_random_body(5))
    assert r.json()["detail"]["code"] == "TOO_MANY_PERSONAS"


def test_fallback_never_exceeds_absolute_max(admin_client, monkeypatch):
    monkeypatch.setattr(settings, "SIM_MAX_PERSONAS", 3)
    assert admin_client.get(API).json()["max_personas"] == 3


def test_candidates_still_return_absolute_max(limit_3):
    n = settings.SIM_MAX_PERSONAS
    r = limit_3.get("/api/simulation/candidates", params={"n": n})
    assert r.status_code == 200
    assert len(r.json()["candidates"]) == n
