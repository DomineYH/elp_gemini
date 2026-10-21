"""발화 상한, 좌석 단위 재생성, 한도·과부하 오류 (#154)."""

import pytest

from app.config import settings


def _create(client, n_phases=2):
    cands = client.get(
        "/api/simulation/candidates", params={"n": 4, "seed": 7}
    ).json()["candidates"]
    body = {
        "personas": [
            {"ref": c["ref"], "pseudonym": c["pseudonym"]} for c in cands
        ],
        "phases": [
            {"name": f"국면{i}", "teacher_prompt": f"발문 {i}"}
            for i in range(n_phases)
        ],
    }
    r = client.post("/api/simulation/sessions", json=body)
    assert r.status_code == 201
    return r.json(), [c["ref"] for c in cands]


@pytest.fixture
def ready(client, teacher, make_upload, fake_gemini):
    make_upload(teacher)
    return client


def _api(sid, path=""):
    return f"/api/simulation/sessions/{sid}{path}"


def _code(r):
    return r.json()["detail"]["code"]


def _teachers(state):
    return [u for u in state["utterances"] if u["speaker_type"] == "teacher"]


def test_one_parse_failure_keeps_others_and_regenerate_fixes_row(
    ready, fake_gemini
):
    state, refs = _create(ready)
    sid = state["session"]["id"]
    failing = state["personas"][1]["id"]
    fake_gemini.parse_fail.add(refs[1])

    turn = ready.post(_api(sid, "/phases/0/enter")).json()
    students = [u for u in turn["utterances"] if u["speaker_type"] == "student"]
    assert len(students) == 4
    assert [u["structured"] is None for u in students] == [
        False,
        True,
        False,
        False,
    ]
    assert students[1]["content"] == "not json"
    assert students[1]["failed"] is True
    assert turn["failed_persona_ids"] == [failing]

    fake_gemini.parse_fail.clear()
    before = ready.get(_api(sid)).json()
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": failing})
    assert r.status_code == 200
    out = r.json()
    assert out["failed_persona_ids"] == []
    [fixed] = out["utterances"]
    assert fixed["id"] == students[1]["id"]
    assert fixed["seq"] == students[1]["seq"]
    assert fixed["structured"] is not None
    assert fixed["failed"] is False

    after = ready.get(_api(sid)).json()
    assert len(after["utterances"]) == len(before["utterances"])
    assert _teachers(after) == _teachers(before)
    assert after["session"]["teacher_turns_used"] == 0


def test_regenerate_healthy_persona_is_409(ready, fake_gemini):
    state, _ = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    calls = fake_gemini.count()
    r = ready.post(
        _api(sid, "/regenerate"),
        json={"persona_id": state["personas"][0]["id"]},
    )
    assert r.status_code == 409
    assert _code(r) == "NOTHING_TO_REGENERATE"
    assert fake_gemini.count() == calls


def test_turn_limit_blocks_say_but_not_transitions(
    ready, fake_gemini, monkeypatch
):
    monkeypatch.setattr(settings, "SIM_MAX_TEACHER_TURNS", 3)
    state, _ = _create(ready, n_phases=3)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    for i in range(3):
        r = ready.post(_api(sid, "/say"), json={"content": f"질문 {i}"})
        assert r.status_code == 200
        assert r.json()["teacher_turns_used"] == i + 1

    calls = fake_gemini.count()
    r = ready.post(_api(sid, "/say"), json={"content": "한 번 더"})
    assert r.status_code == 409
    assert _code(r) == "TURN_LIMIT"
    assert fake_gemini.count() == calls

    # 지도안 발문(plan)은 세지 않는다: 다음 국면 진입 후에도 3
    skip = {"mode": "skip"}
    assert ready.post(_api(sid, "/advance"), json=skip).status_code == 200
    ready.post(_api(sid, "/phases/1/enter"))
    state = ready.get(_api(sid)).json()
    assert state["session"]["teacher_turns_used"] == 3
    assert state["session"]["teacher_turns_max"] == 3
    assert ready.post(_api(sid, "/advance"), json=skip).status_code == 200
    assert ready.post(_api(sid, "/finish")).status_code == 200


@pytest.mark.parametrize(
    "bucket,status,code",
    [
        ("quota", 429, "RESOURCE_EXHAUSTED"),
        ("overload", 503, "MODEL_OVERLOADED"),
    ],
)
def test_gemini_errors_during_say_map_and_persist_nothing(
    ready, fake_gemini, bucket, status, code
):
    state, refs = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    before = ready.get(_api(sid)).json()["utterances"]

    getattr(fake_gemini, bucket).add(refs[2])
    r = ready.post(_api(sid, "/say"), json={"content": "질문"})
    assert r.status_code == status
    assert r.headers["Retry-After"] == "30"
    assert _code(r) == code
    assert ready.get(_api(sid)).json()["utterances"] == before


def test_gemini_error_during_regenerate_keeps_failed_row(ready, fake_gemini):
    state, refs = _create(ready)
    sid = state["session"]["id"]
    failing = state["personas"][0]["id"]
    fake_gemini.parse_fail.add(refs[0])
    ready.post(_api(sid, "/phases/0/enter"))
    before = ready.get(_api(sid)).json()["utterances"]

    fake_gemini.quota.add(refs[0])
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": failing})
    assert r.status_code == 429
    assert ready.get(_api(sid)).json()["utterances"] == before
