"""말하기, 동의/Skip 전이, 종료, 복원 (#153)."""

import pytest
from sqlalchemy import select

from app.models.simulation_utterance import SimulationUtterance
from app.services.simulation import gemini, session_service
from app.services.simulation.llm_schemas import StudentReaction

from .conftest import run


def _reaction(ready):
    return StudentReaction(
        action="고개를 끄덕인다",
        utterance="네!" if ready else "잘 모르겠어요.",
        artifact="",
        misconception="",
        ready_for_next=ready,
        understanding=90 if ready else 40,
        confidence=0.5,
    )


def _create(client, n_phases=5, level="High"):
    cands = client.get(
        "/api/simulation/candidates",
        params={"n": 4, "seed": 7, "level": level},
    ).json()["candidates"]
    body = {
        "personas": [
            {"ref": c["ref"], "pseudonym": c["pseudonym"]} for c in cands
        ],
        "phases": [
            {"name": f"장면{i}", "teacher_prompt": f"발문 {i}"}
            for i in range(n_phases)
        ],
    }
    r = client.post("/api/simulation/sessions", json=body)
    assert r.status_code == 201
    return r.json()


@pytest.fixture
def ready(client, teacher, make_upload, fake_gemini):
    make_upload(teacher)
    return client


def _api(sid, path=""):
    return f"/api/simulation/sessions/{sid}{path}"


def _code(r):
    return r.json()["detail"]["code"]


def test_five_phases_enter_say_agree_to_finished(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    for idx in range(5):
        r = ready.post(_api(sid, f"/phases/{idx}/enter"))
        assert r.status_code == 200
        r = ready.post(_api(sid, "/say"), json={"content": f"질문 {idx}"})
        assert r.status_code == 200
        turn = r.json()
        assert [u["speaker_type"] for u in turn["utterances"]] == [
            "teacher"
        ] + ["student"] * 4
        assert turn["utterances"][0]["structured"] == {"source": "user"}
        assert turn["agreement"]["all_agreed"] is True
        assert turn["agreement"]["count"] == 4
        assert turn["teacher_turns_used"] == idx + 1

        r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
        assert r.status_code == 200
        body = r.json()
        if idx < 4:
            assert body["status"] == "running"
            assert body["current_phase_idx"] == idx + 1
            assert body["next_phase"]["idx"] == idx + 1
            assert body["next_phase"]["name"] == f"장면{idx + 1}"
        else:
            assert body == {
                "status": "finished",
                "current_phase_idx": 4,
                "next_phase": None,
            }

    state = ready.get(_api(sid)).json()
    assert state["session"]["status"] == "finished"
    assert state["session"]["finished_at"] is not None
    systems = [
        (u["phase_idx"], u["structured"])
        for u in state["utterances"]
        if u["speaker_type"] == "system"
    ]
    assert systems[-2:] == [
        (4, {"type": "agree_advance"}),
        (4, {"type": "end", "reason": "last_phase"}),
    ]
    assert [s for _, s in systems].count({"type": "agree_advance"}) == 5


def test_agree_with_one_not_ready_is_409_skip_passes(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    holdout = str(state["personas"][0]["source_record_id"])
    fake_gemini.results["student"] = lambda key: _reaction(key != holdout)
    ready.post(_api(sid, "/phases/0/enter"))
    # 장면 첫 반응은 79로 제한되므로(#302) 한 번 더 말한 뒤 동의를 본다
    turn = ready.post(_api(sid, "/say"), json={"content": "어때?"}).json()
    assert turn["agreement"]["count"] == 3
    assert turn["agreement"]["all_agreed"] is False
    holdout_id = str(state["personas"][0]["id"])
    assert turn["agreement"]["understanding"][holdout_id] == 40

    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 409
    assert _code(r) == "NOT_ALL_AGREED"

    r = ready.post(_api(sid, "/advance"), json={"mode": "skip"})
    assert r.status_code == 200
    assert r.json()["current_phase_idx"] == 1
    state = ready.get(_api(sid)).json()
    assert state["utterances"][-1]["structured"] == {"type": "skip"}
    assert state["utterances"][-1]["phase_idx"] == 0
    # 새 장면은 아직 발화가 없고, 동의는 0
    assert state["agreement"] == {
        "phase_idx": 1,
        "agreed_persona_ids": [],
        "understanding": {str(p["id"]): None for p in state["personas"]},
        "count": 0,
        "total": 4,
        "all_agreed": False,
    }


def test_failed_latest_reaction_keeps_agreement(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    turn = ready.post(_api(sid, "/say"), json={"content": "어때?"}).json()
    assert turn["agreement"]["all_agreed"] is True

    failing = str(state["personas"][0]["source_record_id"])
    fake_gemini.parse_fail.add(failing)
    turn = ready.post(_api(sid, "/say"), json={"content": "하나 더"}).json()
    assert turn["failed_persona_ids"] == [state["personas"][0]["id"]]
    # 파싱 실패는 이전 동의를 유지한다 (#254)
    assert turn["agreement"]["count"] == 4
    failed_id = str(state["personas"][0]["id"])
    assert turn["agreement"]["understanding"][failed_id] == 90

    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 200


def test_support_level_agrees_on_understanding_alone(ready):
    # 교사 도달 게이트는 폐기됐다(#296): 이해도 80 이상이면 바로 동의
    state = _create(ready, level="Poor")
    sid = state["session"]["id"]
    assert {p["adapted_level"] for p in state["personas"]} == {"추가 지원 필요"}
    ready.post(_api(sid, "/phases/0/enter"))
    turn = ready.post(_api(sid, "/say"), json={"content": "어때?"}).json()
    assert turn["agreement"]["count"] == 4
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 200


def test_understanding_drop_after_agree_keeps_agree(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    turn = ready.post(_api(sid, "/say"), json={"content": "어때?"}).json()
    assert turn["agreement"]["all_agreed"] is True

    one = str(state["personas"][0]["source_record_id"])
    one_id = str(state["personas"][0]["id"])
    fake_gemini.results["student"] = lambda key: _reaction(key != one)
    turn = ready.post(_api(sid, "/say"), json={"content": "다시 볼까"}).json()
    assert turn["agreement"]["count"] == 4
    assert turn["agreement"]["understanding"][one_id] == 40
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 200
    rows = ready.get(_api(sid)).json()["utterances"]
    [agree_row] = [
        u for u in rows if u["structured"] == {"type": "agree_advance"}
    ]
    assert agree_row["content"] == "장면0: 전원 동의로 다음 장면"


def test_first_reaction_without_artifact_is_capped_until_say(ready):
    """과업을 아직 하지 않은 장면 첫 반응은 80 미만으로 저장한다 (#302)."""
    state = _create(ready)
    sid = state["session"]["id"]
    ids = [str(p["id"]) for p in state["personas"]]
    turn = ready.post(_api(sid, "/phases/0/enter")).json()
    assert turn["agreement"]["understanding"] == {i: 79 for i in ids}
    assert turn["agreement"]["count"] == 0
    assert turn["agreement"]["all_agreed"] is False
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 409

    turn = ready.post(_api(sid, "/say"), json={"content": "해 볼까?"}).json()
    assert turn["agreement"]["understanding"] == {i: 90 for i in ids}
    assert turn["agreement"]["all_agreed"] is True
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 200


def test_first_reaction_with_artifact_is_not_capped(ready, fake_gemini):
    fake_gemini.results["student"] = _reaction(True).model_copy(
        update={"artifact": "3/4"}
    )
    state = _create(ready)
    sid = state["session"]["id"]
    ids = [str(p["id"]) for p in state["personas"]]
    turn = ready.post(_api(sid, "/phases/0/enter")).json()
    assert turn["agreement"]["understanding"] == {i: 90 for i in ids}
    assert turn["agreement"]["all_agreed"] is True


def test_regenerated_first_reaction_is_capped(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/phases/0/enter"))

    fake_gemini.parse_fail.clear()
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 79


def test_regenerated_later_reaction_is_not_capped(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": "어때?"})

    fake_gemini.parse_fail.clear()
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 90


def test_legacy_row_without_understanding_renders_dash(ready, sim_db):
    state = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))

    async def _strip():
        # #296 이전에 저장된 행처럼 understanding 키를 지운다
        async with sim_db() as db:
            rows = await db.scalars(
                select(SimulationUtterance).where(
                    SimulationUtterance.session_id == sid,
                    SimulationUtterance.speaker_type == "student",
                )
            )
            for u in rows:
                s = dict(u.structured)
                s.pop("understanding")
                u.structured = s
            await db.commit()

    run(_strip())
    agreement = ready.get(_api(sid)).json()["agreement"]
    ids = [p["id"] for p in state["personas"]]
    assert agreement["understanding"] == {str(i): None for i in ids}
    assert agreement["agreed_persona_ids"] == ids


def test_targeted_say_only_target_reacts(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    target = state["personas"][2]
    before = fake_gemini.count("student")
    r = ready.post(
        _api(sid, "/say"),
        json={
            "content": "너는 어떻게 생각해?",
            "target_persona_id": target["id"],
        },
    )
    assert r.status_code == 200
    utts = r.json()["utterances"]
    assert fake_gemini.count("student") == before + 1
    assert fake_gemini.calls[-1] == (
        "student",
        str(target["source_record_id"]),
    )
    assert utts[0]["target_persona_id"] == target["id"]
    assert [(u["speaker_type"], u["persona_id"]) for u in utts[1:]] == [
        ("student", target["id"])
    ]


def test_next_student_call_sees_artifact_but_not_misconception(
    ready, fake_gemini, monkeypatch
):
    """학생 호출 대화록엔 오개념 태그를 넣지 않는다: 옮겨 적기·고착 방지 (#274)."""
    fake_gemini.results["student"] = StudentReaction(
        action="공책에 쓴다",
        utterance="다 했어요",
        artifact="3/4",
        misconception="분모끼리 더함",
        ready_for_next=True,
        understanding=70,
        confidence=0.5,
    )
    prompts = []

    def recording(kind, **kw):
        prompts.append((kind, kw["user"]))
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    sid = _create(ready)["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    prompts.clear()

    r = ready.post(_api(sid, "/say"), json={"content": "다시 볼까?"})
    assert r.status_code == 200
    student = [u for k, u in prompts if k == "student"]
    assert student
    assert all("[산출물: 3/4]" in u for u in student)
    assert not any("[오개념:" in u or "분모끼리 더함" in u for u in student)
    stored = ready.get(_api(sid)).json()["utterances"]
    assert {u["content"] for u in stored if u["speaker_type"] == "student"} == {
        "다 했어요"
    }


def test_student_evidence_keeps_both_tags_for_feedback():
    u = SimulationUtterance(
        speaker_type="student",
        content="다 했어요",
        structured={"artifact": "3/4", "misconception": "분모끼리 더함"},
    )
    assert session_service.student_evidence(u) == (
        "다 했어요 [산출물: 3/4] [오개념: 분모끼리 더함]"
    )


def test_say_guards(ready, as_user, other_teacher):
    state = _create(ready)
    sid = state["session"]["id"]
    r = ready.post(_api(sid, "/say"), json={"content": "안녕"})
    assert r.status_code == 409
    assert _code(r) == "PHASE_NOT_ENTERED"

    ready.post(_api(sid, "/phases/0/enter"))
    r = ready.post(
        _api(sid, "/say"), json={"content": "안녕", "target_persona_id": 999}
    )
    assert r.status_code == 422
    assert _code(r) == "UNKNOWN_PERSONA"
    assert ready.post(_api(sid, "/say"), json={"content": ""}).status_code == (
        422
    )

    as_user(other_teacher)
    for path, body in (
        ("/say", {"content": "안녕"}),
        ("/advance", {"mode": "skip"}),
        ("/finish", None),
    ):
        r = ready.post(_api(sid, path), json=body)
        assert r.status_code == 404
        assert _code(r) == "SESSION_NOT_FOUND"


def test_after_finish_everything_is_409(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    r = ready.post(_api(sid, "/finish"))
    assert r.status_code == 200
    assert r.json() == {"status": "finished"}
    last = ready.get(_api(sid)).json()["utterances"][-1]
    assert last["structured"] == {"type": "end", "reason": "finish"}

    calls = fake_gemini.count()
    for path, body in (
        ("/say", {"content": "안녕"}),
        ("/advance", {"mode": "skip"}),
        ("/advance", {"mode": "agree"}),
        ("/phases/0/enter", None),
        ("/finish", None),
    ):
        r = ready.post(_api(sid, path), json=body)
        assert r.status_code == 409, path
        assert _code(r) == "SESSION_FINISHED"
    assert fake_gemini.count() == calls


def test_restore_returns_everything_in_seq_order(ready, fake_gemini):
    # 산출물이 있는 첫 반응은 79 제한을 받지 않는다(#302): phase 1 진입 직후 동의
    fake_gemini.results["student"] = _reaction(True).model_copy(
        update={"artifact": "메모"}
    )
    state = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    target = state["personas"][1]["id"]
    ready.post(
        _api(sid, "/say"), json={"content": "a", "target_persona_id": target}
    )
    ready.post(_api(sid, "/say"), json={"content": "b"})
    ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    ready.post(_api(sid, "/phases/1/enter"))

    restored = ready.get(_api(sid)).json()
    seqs = [u["seq"] for u in restored["utterances"]]
    assert seqs == list(range(1, len(seqs) + 1))
    assert len(seqs) == (2 + 4) + (1 + 1) + (1 + 4) + 1 + (2 + 4)
    assert len(restored["phases"]) == 5
    assert len(restored["personas"]) == 4
    assert restored["session"]["current_phase_idx"] == 1
    assert restored["agreement"]["phase_idx"] == 1
    assert restored["agreement"]["all_agreed"] is True


# --- 곁가지 반응은 직전 이해도를 유지한다 (#306) ---


def _react(**kw):
    # model_copy와 달리 검증기(오개념 79 상한)를 거친다
    return StudentReaction(**{**_reaction(False).model_dump(), **kw})


def _enter_then_say(client, fake_gemini, first, then):
    state = _create(client)
    sid = state["session"]["id"]
    fake_gemini.results["student"] = first
    client.post(_api(sid, "/phases/0/enter"))
    fake_gemini.results["student"] = then
    turn = client.post(_api(sid, "/say"), json={"content": "인구는?"}).json()
    return state, turn


def _stored(turn):
    return {
        u["structured"]["understanding"]
        for u in turn["utterances"]
        if u["speaker_type"] == "student"
    }


def test_off_task_reaction_cannot_raise_to_agree(ready, fake_gemini):
    state, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=40),
        _react(on_task=False, understanding=82, artifact="우리 동네 인구"),
    )
    ids = [str(p["id"]) for p in state["personas"]]
    assert _stored(turn) == {40}
    assert turn["agreement"]["understanding"] == {i: 40 for i in ids}
    assert turn["agreement"]["agreed_persona_ids"] == []
    assert turn["agreement"]["all_agreed"] is False


def test_off_task_reaction_cannot_drop_bar(ready, fake_gemini):
    state, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=90, artifact="3/4"),
        _react(on_task=False, understanding=30),
    )
    ids = [str(p["id"]) for p in state["personas"]]
    assert _stored(turn) == {90}
    assert turn["agreement"]["understanding"] == {i: 90 for i in ids}
    assert turn["agreement"]["all_agreed"] is True


def test_on_task_reaction_is_not_corrected(ready, fake_gemini):
    state, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=40),
        _react(on_task=True, understanding=82),
    )
    assert _stored(turn) == {82}
    assert turn["agreement"]["all_agreed"] is True


@pytest.mark.parametrize("artifact, expected", [("", 79), ("3/4", 85)])
def test_off_task_first_reaction_only_gets_first_cap(
    ready, fake_gemini, artifact, expected
):
    fake_gemini.results["student"] = _react(
        on_task=False, understanding=85, artifact=artifact
    )
    sid = _create(ready)["session"]["id"]
    turn = ready.post(_api(sid, "/phases/0/enter")).json()
    assert _stored(turn) == {expected}


def test_off_task_misconception_keeps_validator_cap(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=60),
        _react(on_task=False, misconception="분모끼리 더함", understanding=85),
    )
    assert _stored(turn) == {79}


def test_regenerated_off_task_reaction_keeps_previous(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.results["student"] = _react(understanding=40)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": "인구는?"})

    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(on_task=False, understanding=82)
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 40


def test_student_call_sees_own_previous_understanding(
    ready, fake_gemini, monkeypatch
):
    state = _create(ready)
    sid = state["session"]["id"]
    keys = [str(p["source_record_id"]) for p in state["personas"]]
    values = {k: 41 + i for i, k in enumerate(keys)}
    fake_gemini.results["student"] = lambda key: _react(
        understanding=values[key]
    )
    prompts = []

    def recording(kind, **kw):
        prompts.append((kw["persona_key"], kw["user"]))
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    ready.post(_api(sid, "/phases/0/enter"))
    assert prompts and not any("[직전 이해도]" in u for _, u in prompts)

    prompts.clear()
    ready.post(_api(sid, "/say"), json={"content": "인구는?"})
    assert {k: u for k, u in prompts}.keys() == set(keys)
    for k, u in prompts:
        assert f"[직전 이해도] {values[k]}\n[이번 장면 대화]" in u

    prompts.clear()
    target = state["personas"][2]
    ready.post(
        _api(sid, "/say"),
        json={"content": "너는?", "target_persona_id": target["id"]},
    )
    [(k, u)] = prompts
    assert k == keys[2]
    assert [ln for ln in u.splitlines() if ln.startswith("[직전 이해도]")] == [
        f"[직전 이해도] {values[k]}"
    ]
