"""발화 상한, 좌석 단위 재생성, 한도·과부하 오류 (#154)."""

import sqlite3

import pytest

from app.config import settings
from app.services.simulation import gemini, session_service


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
        ("timeout", 503, "MODEL_TIMEOUT"),
        ("transport", 503, "MODEL_UNAVAILABLE"),
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


def test_enter_timeout_is_503_and_stores_nothing(ready, fake_gemini):
    state, refs = _create(ready)
    sid = state["session"]["id"]
    fake_gemini.timeout.add(refs[1])

    r = ready.post(_api(sid, "/phases/0/enter"))
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "30"
    assert _code(r) == "MODEL_TIMEOUT"
    assert ready.get(_api(sid)).json()["utterances"] == []


def test_enter_transport_error_is_503_and_stores_nothing(ready, fake_gemini):
    state, refs = _create(ready)
    sid = state["session"]["id"]
    fake_gemini.transport.add(refs[1])

    r = ready.post(_api(sid, "/phases/0/enter"))
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "30"
    assert _code(r) == "MODEL_UNAVAILABLE"
    assert ready.get(_api(sid)).json()["utterances"] == []


def test_timeout_wins_over_transport_error(ready, fake_gemini):
    state, refs = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))

    fake_gemini.timeout.add(refs[0])
    fake_gemini.transport.add(refs[1])
    r = ready.post(_api(sid, "/say"), json={"content": "질문"})
    assert r.status_code == 503
    assert _code(r) == "MODEL_TIMEOUT"


def test_quota_wins_over_timeout(ready, fake_gemini):
    state, refs = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))

    fake_gemini.quota.add(refs[0])
    fake_gemini.timeout.add(refs[1])
    r = ready.post(_api(sid, "/say"), json={"content": "질문"})
    assert r.status_code == 429
    assert _code(r) == "RESOURCE_EXHAUSTED"


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


# 다른 탭의 교사 발화(source=user) 1건
OTHER_TAB_TURN = (
    "INSERT INTO simulation_utterances (session_id, phase_idx, seq,"
    " speaker_type, content, structured) VALUES"
    " (1, 0, 900, 'teacher', '다른 탭', '{\"source\": \"user\"}')"
)


def _during_call(monkeypatch, fake_gemini, db_path, sql):
    """Gemini 호출 중에 다른 요청이 DB를 바꾼 상황을 만든다."""

    def wrapped(kind, **kw):
        conn = sqlite3.connect(db_path)
        with conn:
            conn.executescript(sql)
        conn.close()
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", wrapped)


@pytest.mark.parametrize(
    "sql,code",
    [
        (
            "UPDATE simulation_sessions SET status='finished'",
            "SESSION_FINISHED",
        ),
        (
            "UPDATE simulation_sessions SET current_phase_idx=1",
            "CONFLICT_RETRY",
        ),
        (OTHER_TAB_TURN, "TURN_LIMIT"),
    ],
)
def test_say_rechecks_session_after_gemini_and_persists_nothing(
    ready, fake_gemini, monkeypatch, tmp_path, sql, code
):
    monkeypatch.setattr(settings, "SIM_MAX_TEACHER_TURNS", 1)
    state, _ = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    before = [u["seq"] for u in ready.get(_api(sid)).json()["utterances"]]

    _during_call(monkeypatch, fake_gemini, tmp_path / "sim.db", sql)
    target = state["personas"][0]["id"]
    r = ready.post(
        _api(sid, "/say"), json={"content": "질문", "target_persona_id": target}
    )
    assert r.status_code == 409
    assert _code(r) == code
    after = [u["seq"] for u in ready.get(_api(sid)).json()["utterances"]]
    assert [s for s in after if s != 900] == before


def test_regenerate_after_concurrent_finish_keeps_failed_row(
    ready, fake_gemini, monkeypatch, tmp_path
):
    state, refs = _create(ready)
    sid = state["session"]["id"]
    failing = state["personas"][0]["id"]
    fake_gemini.parse_fail.add(refs[0])
    ready.post(_api(sid, "/phases/0/enter"))
    before = ready.get(_api(sid)).json()["utterances"]

    fake_gemini.parse_fail.clear()
    _during_call(
        monkeypatch,
        fake_gemini,
        tmp_path / "sim.db",
        "UPDATE simulation_sessions SET status='finished'",
    )
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": failing})
    assert r.status_code == 409
    assert _code(r) == "SESSION_FINISHED"
    assert ready.get(_api(sid)).json()["utterances"] == before


# 다른 탭이 같은 국면 진입을 먼저 끝냈다 (호출마다 실행되므로 OR IGNORE)
OTHER_TAB_ENTER = (
    "INSERT OR IGNORE INTO simulation_utterances (session_id, phase_idx,"
    " seq, speaker_type, content, structured) VALUES"
    " (1, 0, 900, 'system', '다른 탭 시작', '{\"type\": \"phase_enter\"}'),"
    " (1, 0, 901, 'teacher', '다른 탭 발문', '{\"source\": \"plan\"}');"
)
OTHER_TAB_FINISH = (
    "UPDATE simulation_sessions SET status='finished';"
    " INSERT OR IGNORE INTO simulation_utterances (session_id, phase_idx,"
    " seq, speaker_type, content, structured) VALUES"
    " (1, 0, 900, 'system', '수업 종료', '{\"type\": \"end\"}');"
)


def test_enter_returns_batch_stored_by_other_tab_during_gemini(
    ready, fake_gemini, monkeypatch, tmp_path
):
    sid = _create(ready)[0]["session"]["id"]
    _during_call(monkeypatch, fake_gemini, tmp_path / "sim.db", OTHER_TAB_ENTER)
    r = ready.post(_api(sid, "/phases/0/enter"))
    assert r.status_code == 200
    assert [u["seq"] for u in r.json()["utterances"]] == [900, 901]
    utts = ready.get(_api(sid)).json()["utterances"]
    assert [u["seq"] for u in utts] == [900, 901]


@pytest.mark.parametrize(
    "sql,code",
    [
        (OTHER_TAB_FINISH, "SESSION_FINISHED"),
        (
            "UPDATE simulation_sessions SET current_phase_idx=1",
            "PHASE_NOT_CURRENT",
        ),
    ],
)
def test_enter_rechecks_session_after_gemini_and_persists_nothing(
    ready, fake_gemini, monkeypatch, tmp_path, sql, code
):
    sid = _create(ready)[0]["session"]["id"]
    _during_call(monkeypatch, fake_gemini, tmp_path / "sim.db", sql)
    r = ready.post(_api(sid, "/phases/0/enter"))
    assert r.status_code == 409
    assert _code(r) == code
    utts = ready.get(_api(sid)).json()["utterances"]
    assert [u["seq"] for u in utts] == ([900] if "end" in sql else [])


def _at_next_seq(monkeypatch, db_path, sql):
    """재확인 뒤 seq를 잡는 순간에 다른 탭이 커밋을 시도한다.

    돌려주는 목록에 그 시도의 결과(성공이면 None, 실패면 오류 문구)가 담긴다.
    """
    original, outcomes = session_service.next_seq, []

    async def wrapped(db, sid):
        if not outcomes:
            conn = sqlite3.connect(db_path, timeout=0.2)
            try:
                with conn:
                    conn.executescript(sql)
                outcomes.append(None)
            except sqlite3.OperationalError as e:
                outcomes.append(str(e))
            finally:
                conn.close()
        return await original(db, sid)

    monkeypatch.setattr(session_service, "next_seq", wrapped)
    return outcomes


def test_enter_holds_lock_so_other_tab_cannot_add_second_batch(
    ready, fake_gemini, monkeypatch, tmp_path
):
    sid = _create(ready)[0]["session"]["id"]
    outcomes = _at_next_seq(monkeypatch, tmp_path / "sim.db", OTHER_TAB_ENTER)
    r = ready.post(_api(sid, "/phases/0/enter"))
    assert r.status_code == 200
    assert outcomes == ["database is locked"]
    utts = ready.get(_api(sid)).json()["utterances"]
    enters = [u for u in utts if u["speaker_type"] == "system"]
    assert len(enters) == 1
    assert len(utts) == 2 + 4


def test_say_holds_lock_so_finish_cannot_end_before_its_rows(
    ready, fake_gemini, monkeypatch, tmp_path
):
    state, _ = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    outcomes = _at_next_seq(monkeypatch, tmp_path / "sim.db", OTHER_TAB_FINISH)
    r = ready.post(_api(sid, "/say"), json={"content": "질문"})
    assert r.status_code == 200
    assert outcomes == ["database is locked"]
    after = ready.get(_api(sid)).json()
    assert after["session"]["status"] == "running"
    assert not [
        u for u in after["utterances"] if u["speaker_type"] == "system"
    ][1:]


def test_regenerate_foreign_persona_is_422(ready, fake_gemini):
    state, _ = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": 99999})
    assert r.status_code == 422
    assert _code(r) == "UNKNOWN_PERSONA"


def test_say_accepts_a_full_length_plan_prompt(ready):
    # 지도안 발문(국면 teacher_prompt)은 그대로 보낼 수 있어야 한다
    cands = ready.get(
        "/api/simulation/candidates", params={"n": 4, "seed": 7}
    ).json()["candidates"]
    prompt = "가" * 1500
    r = ready.post(
        "/api/simulation/sessions",
        json={
            "personas": [
                {"ref": c["ref"], "pseudonym": c["pseudonym"]} for c in cands
            ],
            "phases": [{"name": "도입", "teacher_prompt": prompt}],
        },
    )
    assert r.status_code == 201
    sid = r.json()["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))

    assert (
        ready.post(_api(sid, "/say"), json={"content": prompt}).status_code
        == 200
    )
    too_long = ready.post(_api(sid, "/say"), json={"content": "가" * 2001})
    assert too_long.status_code == 422


def test_say_whitespace_only_is_422_and_persists_nothing(ready, fake_gemini):
    state, _ = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    before = ready.get(_api(sid)).json()
    calls = fake_gemini.count("student")

    r = ready.post(_api(sid, "/say"), json={"content": "   "})
    assert r.status_code == 422

    after = ready.get(_api(sid)).json()
    assert _teachers(after) == _teachers(before)
    assert after["session"]["teacher_turns_used"] == 0
    assert fake_gemini.count("student") == calls


def test_create_session_rejects_whitespace_teacher_prompt(ready):
    cands = ready.get(
        "/api/simulation/candidates", params={"n": 4, "seed": 7}
    ).json()["candidates"]
    r = ready.post(
        "/api/simulation/sessions",
        json={
            "personas": [
                {"ref": c["ref"], "pseudonym": c["pseudonym"]} for c in cands
            ],
            "phases": [{"name": "도입", "teacher_prompt": " "}],
        },
    )
    assert r.status_code == 422


def test_get_session_with_legacy_whitespace_phase_is_200(ready, tmp_path):
    # 입력 strip 이전에 저장된 공백 국면도 응답 모델이 그대로 읽어야 한다.
    state, _ = _create(ready)
    sid = state["session"]["id"]
    conn = sqlite3.connect(tmp_path / "sim.db")
    with conn:
        conn.execute(
            "UPDATE simulation_phases SET name='   ', teacher_prompt='   '"
            " WHERE session_id=? AND idx=0",
            (sid,),
        )
    conn.close()

    r = ready.get(_api(sid))
    assert r.status_code == 200
    assert r.json()["phases"][0]["teacher_prompt"] == "   "
