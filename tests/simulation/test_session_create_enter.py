"""세션 생성과 첫 국면 진입 (#152)."""

import pytest
from sqlalchemy import func, select

from app.models.simulation_session import SimulationSession
from app.models.simulation_utterance import SimulationUtterance

from .conftest import run


def _phases(n=3):
    names = [
        "도입",
        "활동1",
        "활동2",
        "활동3",
        "활동4",
        "활동5",
        "활동6",
        "정리",
    ]
    return [
        {
            "name": names[i % len(names)],
            "minutes": 5,
            "teacher_prompt": f"발문 {i}",
        }
        for i in range(n)
    ]


def _candidates(client, n=4, seed=7):
    return client.get(
        "/api/simulation/candidates", params={"n": n, "seed": seed}
    ).json()["candidates"]


def _explicit_body(client, n=4):
    cands = _candidates(client, n)
    return {
        "personas": [
            {"ref": c["ref"], "pseudonym": c["pseudonym"]} for c in cands
        ],
        "phases": _phases(),
    }


def _count(sim_db, column):
    async def _go():
        async with sim_db() as db:
            return await db.scalar(select(func.count(column)))

    return run(_go())


@pytest.fixture
def ready(client, teacher, make_upload, fake_gemini):
    make_upload(teacher)
    return client


def test_explicit_create_saves_personas_in_request_order(ready, fake_gemini):
    body = _explicit_body(ready)
    r = ready.post("/api/simulation/sessions", json=body)
    assert r.status_code == 201
    state = r.json()
    assert state["session"]["status"] == "running"
    assert state["session"]["current_phase_idx"] == 0
    assert state["session"]["persona_count"] == 4
    assert [p["name"] for p in state["phases"]] == ["도입", "활동1", "활동2"]
    personas = state["personas"]
    assert [p["display_name"] for p in personas] == [
        p["pseudonym"] for p in body["personas"]
    ]
    assert [p["source_record_id"] for p in personas] == [
        int(p["ref"]) for p in body["personas"]
    ]
    assert [p["color_key"] for p in personas] == ["p1", "p2", "p3", "p4"]
    assert all(p["source"] == "dataset" for p in personas)
    assert personas[0]["adapted_profile"]["behavior_summary"]
    assert {p["adapted_level"] for p in personas} == {
        "높은 도달",
        "안정적 도달",
        "부분 도달",
        "추가 지원 필요",
    }
    assert "raw_profile" not in personas[0]
    assert state["utterances"] == []
    assert fake_gemini.count("adapt") == 4


def test_random_create_matches_candidates_for_same_seed(ready):
    cands = _candidates(ready, n=3, seed=11)
    r = ready.post(
        "/api/simulation/sessions",
        json={
            "random": {"n": 3, "grade": "all", "level": "all", "seed": 11},
            "phases": _phases(),
        },
    )
    assert r.status_code == 201
    personas = r.json()["personas"]
    assert [p["display_name"] for p in personas] == [
        c["pseudonym"] for c in cands
    ]
    assert [str(p["source_record_id"]) for p in personas] == [
        c["ref"] for c in cands
    ]


@pytest.mark.parametrize("n", [1, 7])
def test_persona_count_out_of_range_is_422(ready, sim_db, n):
    body = {
        "random": {"n": n, "grade": "all", "level": "all", "seed": 1},
        "phases": _phases(),
    }
    assert ready.post("/api/simulation/sessions", json=body).status_code == 422
    explicit = _explicit_body(ready, n=6)
    explicit["personas"] = (explicit["personas"] * 2)[:n]
    assert (
        ready.post("/api/simulation/sessions", json=explicit).status_code == 422
    )
    assert _count(sim_db, SimulationSession.id) == 0


@pytest.mark.parametrize("n", [0, 9])
def test_phase_count_out_of_range_is_422(ready, n):
    body = _explicit_body(ready)
    body["phases"] = _phases(n)
    assert ready.post("/api/simulation/sessions", json=body).status_code == 422


def test_both_or_neither_selection_is_422(ready):
    body = _explicit_body(ready)
    body["random"] = {"n": 4, "grade": "all", "level": "all", "seed": 1}
    assert ready.post("/api/simulation/sessions", json=body).status_code == 422
    assert (
        ready.post(
            "/api/simulation/sessions", json={"phases": _phases()}
        ).status_code
        == 422
    )


def test_bad_pseudonym_and_unknown_ref(ready):
    body = _explicit_body(ready)
    body["personas"][1]["pseudonym"] = body["personas"][0]["pseudonym"]
    r = ready.post("/api/simulation/sessions", json=body)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "DUPLICATE_PSEUDONYM"

    body = _explicit_body(ready)
    body["personas"][0]["pseudonym"] = "홍길동"
    r = ready.post("/api/simulation/sessions", json=body)
    assert r.json()["detail"]["code"] == "DUPLICATE_PSEUDONYM"

    body = _explicit_body(ready)
    body["personas"][0]["ref"] = "custom:1"
    r = ready.post("/api/simulation/sessions", json=body)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "UNKNOWN_PERSONA"


def test_adapt_parse_fail_on_one_ref_creates_nothing(
    ready, sim_db, fake_gemini
):
    body = _explicit_body(ready)
    fake_gemini.parse_fail.add(body["personas"][2]["ref"])
    r = ready.post("/api/simulation/sessions", json=body)
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "ADAPT_FAILED"
    assert _count(sim_db, SimulationSession.id) == 0


def test_adapt_quota_on_one_ref_is_429_and_creates_nothing(
    ready, sim_db, fake_gemini
):
    body = _explicit_body(ready)
    fake_gemini.quota.add(body["personas"][1]["ref"])
    r = ready.post("/api/simulation/sessions", json=body)
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "30"
    assert r.json()["detail"]["code"] == "RESOURCE_EXHAUSTED"
    assert _count(sim_db, SimulationSession.id) == 0


def test_create_without_upload_is_404(client, fake_gemini):
    r = client.post(
        "/api/simulation/sessions",
        json={
            "random": {"n": 2, "grade": "all", "level": "all", "seed": 1},
            "phases": _phases(),
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NO_UPLOAD"


def _create(client):
    r = client.post("/api/simulation/sessions", json=_explicit_body(client))
    assert r.status_code == 201
    return r.json()


def test_enter_phase_zero_writes_system_teacher_students(
    ready, sim_db, fake_gemini
):
    state = _create(ready)
    sid = state["session"]["id"]
    r = ready.post(f"/api/simulation/sessions/{sid}/phases/0/enter")
    assert r.status_code == 200
    turn = r.json()
    utts = turn["utterances"]
    assert [u["seq"] for u in utts] == [1, 2, 3, 4, 5, 6]
    assert [u["speaker_type"] for u in utts] == ["system", "teacher"] + [
        "student"
    ] * 4
    assert utts[0]["structured"] == {"type": "phase_enter"}
    assert utts[1]["structured"] == {"source": "plan"}
    assert utts[1]["content"] == "발문 0"
    assert [u["persona_id"] for u in utts[2:]] == [
        p["id"] for p in state["personas"]
    ]
    for u in utts[2:]:
        assert u["structured"]["ready_for_next"] is True
        assert u["failed"] is False
        assert u["model_name"] == "fake-model"
        assert u["latency_ms"] == 1
    assert turn["failed_persona_ids"] == []
    assert turn["teacher_turns_used"] == 0

    async def _temps():
        async with sim_db() as db:
            rows = await db.scalars(
                select(SimulationUtterance.temperature).where(
                    SimulationUtterance.speaker_type == "student"
                )
            )
            return set(rows)

    assert run(_temps()) == {1.0}

    restored = ready.get(f"/api/simulation/sessions/{sid}").json()
    assert restored["utterances"] == utts


def test_second_enter_returns_stored_copy(ready, fake_gemini):
    sid = _create(ready)["session"]["id"]
    first = ready.post(f"/api/simulation/sessions/{sid}/phases/0/enter").json()
    calls = fake_gemini.count("student")
    second = ready.post(f"/api/simulation/sessions/{sid}/phases/0/enter")
    assert second.status_code == 200
    assert second.json()["utterances"] == first["utterances"]
    assert fake_gemini.count("student") == calls


def test_enter_other_phase_is_409(ready):
    sid = _create(ready)["session"]["id"]
    r = ready.post(f"/api/simulation/sessions/{sid}/phases/1/enter")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "PHASE_NOT_CURRENT"


def test_enter_student_quota_is_429_and_writes_nothing(
    ready, sim_db, fake_gemini
):
    state = _create(ready)
    sid = state["session"]["id"]
    fake_gemini.overload.add("student")
    r = ready.post(f"/api/simulation/sessions/{sid}/phases/0/enter")
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "30"
    assert _count(sim_db, SimulationUtterance.id) == 0


def test_other_user_gets_404(ready, as_user, other_teacher):
    sid = _create(ready)["session"]["id"]
    as_user(other_teacher)
    r = ready.get(f"/api/simulation/sessions/{sid}")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"
    r = ready.post(f"/api/simulation/sessions/{sid}/phases/0/enter")
    assert r.status_code == 404
    page = ready.get(f"/simulation/sessions/{sid}")
    assert page.status_code == 404


def test_run_page_renders_for_owner(ready):
    sid = _create(ready)["session"]["id"]
    page = ready.get(f"/simulation/sessions/{sid}")
    assert page.status_code == 200
    assert "pb-28" in page.text
    assert "lg:grid-cols-4" in page.text


def test_draft_is_fallback_rows_or_no_upload(
    client, teacher, make_upload, fake_gemini
):
    fake_gemini.parse_fail.add("phase_split")  # 분해 실패 → 폴백 (#155)
    r = client.get("/api/simulation/phases/draft")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NO_UPLOAD"
    make_upload(teacher)
    body = client.get("/api/simulation/phases/draft").json()
    assert body["source"] == "fallback"
    assert [p["name"] for p in body["phases"]] == ["도입", "활동1", "정리"]


def test_setup_page_has_phase_panel_and_start_button(
    client, teacher, make_upload
):
    make_upload(teacher)
    page = client.get("/simulation/setup").text
    assert 'id="phasePanel"' in page
    assert "시뮬레이션 시작" in page
