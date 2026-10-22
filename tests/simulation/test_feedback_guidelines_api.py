"""관리자 피드백 지침 API: 버전 저장·권한·CSRF·미리보기·버전 기록 (#159)."""

import re

import pytest
from sqlalchemy import event, func, inspect, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import ensure_simulation_tables
from app.models.simulation_feedback_guideline import (
    SimulationFeedbackGuideline,
)
from app.models.simulation_session import SimulationSession
from app.services.simulation import feedback
from app.utils.admin_csrf import ADMIN_CSRF_HEADER
from tests.simulation.conftest import run
from tests.simulation.test_feedback import _finished

PAGE = "/admin/simulation/settings"
API = "/admin/api/simulation/feedback-guidelines"
BODY = {
    "enabled": True,
    "required_aspects": ["udl"],
    "criteria_ids": [],
    "extra_instructions": "협동학습 장면을 짚어 주세요.",
}


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


def test_each_save_is_a_new_version(admin_client):
    r1 = admin_client.post(API, json=BODY)
    assert r1.status_code == 201
    assert r1.json()["version"] == 1
    r2 = admin_client.post(API, json={**BODY, "enabled": False})
    assert r2.status_code == 201
    assert r2.json()["version"] == 2

    got = admin_client.get(API).json()
    assert got["current"]["version"] == 2
    assert got["current"]["enabled"] is False
    assert [h["version"] for h in got["history"]] == [2, 1]
    assert got["history"][0]["created_at"].endswith("+00:00")
    assert len(got["aspects"]["fixed"]) == 3
    assert got["base_prompt"]


def test_non_admin_is_refused(client):
    assert client.get(PAGE).status_code == 403
    assert client.get(API).status_code == 403
    assert client.post(API, json=BODY).status_code == 403
    assert client.post(f"{API}/preview", json=BODY).status_code == 403


def test_post_without_csrf_header_is_refused(admin_client):
    del admin_client.headers[ADMIN_CSRF_HEADER]
    assert admin_client.post(API, json=BODY).status_code == 403
    assert admin_client.post(f"{API}/preview", json=BODY).status_code == 403
    admin_client.headers[ADMIN_CSRF_HEADER] = "wrong"
    assert admin_client.post(API, json=BODY).status_code == 403
    assert admin_client.get(API).json()["history"] == []


def _guideline_rows(sim_db):
    async def _go():
        async with sim_db() as db:
            return await db.scalar(
                select(func.count(SimulationFeedbackGuideline.id))
            )

    return run(_go())


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "REPORTS_DIR", str(tmp_path / "reports"))


def test_preview_uses_own_finished_session_and_saves_nothing(
    admin_client, admin, make_upload, fake_gemini, reports, sim_db
):
    make_upload(admin)
    sid = _finished(admin_client)

    r = admin_client.post(f"{API}/preview", json=BODY)
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"]["risk_scenarios"][0]["title"] == "전이 지연"
    assert body["model_name"] == "fake-model"
    assert fake_gemini.count("feedback") == 1
    assert _guideline_rows(sim_db) == 0
    # 미리보기는 세션 피드백 캐시도 채우지 않는다
    r = admin_client.get(f"/api/simulation/sessions/{sid}/feedback")
    assert r.status_code == 404


def test_preview_without_own_finished_session_is_409(
    client, as_user, teacher, admin, make_upload, fake_gemini, reports
):
    make_upload(teacher)
    _finished(client)
    as_user(admin)
    client.headers[ADMIN_CSRF_HEADER] = _token(client)

    r = client.post(f"{API}/preview", json=BODY)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NO_SAMPLE_SESSION"
    assert fake_gemini.count("feedback") == 0


def _feedback_after_save(client, as_user, teacher, admin, body):
    as_user(admin)
    client.headers[ADMIN_CSRF_HEADER] = _token(client)
    assert client.post(API, json=body).status_code == 201
    as_user(teacher)
    sid = _finished(client)
    r = client.post(f"/api/simulation/sessions/{sid}/feedback")
    assert r.status_code == 200
    md = client.get(f"/api/simulation/sessions/{sid}/feedback/download").text
    return sid, r.json(), md


def _session_version(sim_db, sid):
    async def _go():
        async with sim_db() as db:
            session = await db.get(SimulationSession, sid)
            return session.feedback_guideline_version

    return run(_go())


def test_feedback_records_enabled_guideline_version(
    client, as_user, teacher, admin, make_upload, fake_gemini, reports, sim_db
):
    make_upload(teacher)
    sid, envelope, md = _feedback_after_save(
        client, as_user, teacher, admin, BODY
    )
    assert envelope["guideline_version"] == 1
    assert _session_version(sim_db, sid) == 1
    assert "커스텀 v1" in md


def test_disabled_guideline_records_default(
    client, as_user, teacher, admin, make_upload, fake_gemini, reports, sim_db
):
    make_upload(teacher)
    sid, envelope, md = _feedback_after_save(
        client, as_user, teacher, admin, {**BODY, "enabled": False}
    )
    assert envelope["guideline_version"] is None
    assert _session_version(sim_db, sid) is None
    assert "적용 지침: 기본값" in md


def test_guideline_model_matches_ddl(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'g.db'}")

    async def _cols():
        await ensure_simulation_tables(engine)
        async with engine.connect() as conn:
            cols = await conn.run_sync(
                lambda c: inspect(c).get_columns(
                    "simulation_feedback_guidelines"
                )
            )
        await engine.dispose()
        return {col["name"] for col in cols}

    table = SimulationFeedbackGuideline.__table__
    assert run(_cols()) == {c.name for c in table.columns}


def test_concurrent_save_with_same_version_is_409(admin_client, sim_db):
    table = SimulationFeedbackGuideline.__table__

    def other_save_first(mapper, connection, target):
        # 다른 관리자의 저장이 같은 version을 먼저 넣은 상황
        connection.execute(
            table.insert().values(
                version=target.version, required_aspects=[], criteria_ids=[]
            )
        )

    event.listen(SimulationFeedbackGuideline, "before_insert", other_save_first)
    try:
        r = admin_client.post(API, json=BODY)
    finally:
        event.remove(
            SimulationFeedbackGuideline, "before_insert", other_save_first
        )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CONFLICT_RETRY"
    assert admin_client.post(API, json=BODY).status_code == 201
