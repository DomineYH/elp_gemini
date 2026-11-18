"""말하기, 동의/Skip 전이, 종료, 복원 (#153)."""

import itertools

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
        on_task=True,
    )


_n = itertools.count(1)


def _fresh(reaction):
    """맞장구·같은 말 되풀이는 이해도가 오르지 않으므로(#352) 내용 있는 새 말로 바꾼다."""
    return reaction.model_copy(
        update={"utterance": f"자료 {next(_n)}번에서 답을 찾았어요."}
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
    # 기본 반응이 같은 말을 되풀이하면 say에서 오르지 않는다 (#352)
    default = fake_gemini.results["student"]
    fake_gemini.results["student"] = lambda key: _fresh(default)
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
    fake_gemini.results["student"] = lambda key: _fresh(
        _reaction(key != holdout)
    )
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
        "pledged_persona_ids": [],
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


def test_first_reaction_with_artifact_is_capped_until_say(ready, fake_gemini):
    """산출물이 있어도 장면 첫 반응은 80 미만으로 저장한다 (#318)."""
    # 같은 산출물을 짧게 다시 말하거나(#319) 자기 직전 말을 되풀이하면(#336)
    # 오르지 않으므로 풀이를 말로 설명하고, say에서는 다르게 설명한다
    fake_gemini.results["student"] = _reaction(True).model_copy(
        update={"artifact": "3/4", "utterance": "분모를 같게 만들어서 더했어요"}
    )
    state = _create(ready)
    sid = state["session"]["id"]
    ids = [str(p["id"]) for p in state["personas"]]
    turn = ready.post(_api(sid, "/phases/0/enter")).json()
    assert turn["agreement"]["understanding"] == {i: 79 for i in ids}
    assert turn["agreement"]["all_agreed"] is False
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 409

    fake_gemini.results["student"] = fake_gemini.results["student"].model_copy(
        update={"utterance": "분모를 4로 같게 해서 1/4하고 2/4를 더했어요"}
    )
    turn = ready.post(_api(sid, "/say"), json={"content": "해 볼까?"}).json()
    assert turn["agreement"]["understanding"] == {i: 90 for i in ids}
    assert turn["agreement"]["all_agreed"] is True
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 200


@pytest.mark.parametrize("artifact", ["", "3/4"])
def test_regenerated_first_reaction_is_capped(ready, fake_gemini, artifact):
    fake_gemini.results["student"] = _reaction(True).model_copy(
        update={"artifact": artifact}
    )
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
        on_task=True,
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
    assert all("의 산출물: 3/4]" in u for u in student)
    # 주인 없는 산출물 태그는 없다 (#348)
    assert not any("[산출물:" in u for u in student)
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


def test_transcript_line_labels_artifact_with_owner():
    """남의 산출물 태그를 옮겨 적지 않도록 주인 이름을 붙인다 (#348)."""
    u = SimulationUtterance(
        speaker_type="student",
        persona_id=1,
        content="네",
        structured={"artifact": "3/4", "misconception": "분모끼리 더함"},
    )
    assert session_service._transcript_line(u, {1: "현우"}) == (
        "현우: 네 [현우의 산출물: 3/4]"
    )


def test_transcript_line_without_artifact_has_no_tag():
    u = SimulationUtterance(
        speaker_type="student", persona_id=1, content="몰라요", structured={}
    )
    assert session_service._transcript_line(u, {1: "현우"}) == "현우: 몰라요"


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
    # 장면 첫 반응은 79로 제한되므로(#318) 한 번 더 말해 동의를 만든다
    ready.post(_api(sid, "/say"), json={"content": "c"})

    restored = ready.get(_api(sid)).json()
    seqs = [u["seq"] for u in restored["utterances"]]
    assert seqs == list(range(1, len(seqs) + 1))
    assert len(seqs) == (2 + 4) + (1 + 1) + (1 + 4) + 1 + (2 + 4) + (1 + 4)
    assert len(restored["phases"]) == 5
    assert len(restored["personas"]) == 4
    assert restored["session"]["current_phase_idx"] == 1
    assert restored["agreement"]["phase_idx"] == 1
    assert restored["agreement"]["all_agreed"] is True


# --- 곁가지 반응은 직전 이해도를 유지한다 (#306) ---


# 서술문이 있어야 오개념이 남는다: 막힘뿐인 반응은 비워진다 (#330)
STATEMENT = "분모끼리 더하면 돼요."


def _react(**kw):
    # model_copy와 달리 검증기(오개념 79 상한)를 거친다
    return StudentReaction(**{**_reaction(False).model_dump(), **kw})


def _enter_then_say(client, fake_gemini, first, then, content="인구는?"):
    state = _create(client)
    sid = state["session"]["id"]
    fake_gemini.results["student"] = first
    client.post(_api(sid, "/phases/0/enter"))
    fake_gemini.results["student"] = then
    turn = client.post(_api(sid, "/say"), json={"content": content}).json()
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
    # 장면 첫 반응은 79로 제한되므로(#318) 한 번 더 말해 90에 올린 뒤 곁가지를 본다
    state, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=90, artifact="3/4"),
        # 같은 산출물을 짧게 다시 말하면 오르지 않으므로(#319) 풀이를 말로 설명한다
        _react(
            understanding=90,
            artifact="3/4",
            utterance="분모를 같게 만들어서 더했어요",
        ),
    )
    assert _stored(turn) == {90}
    fake_gemini.results["student"] = _react(on_task=False, understanding=30)
    sid = state["session"]["id"]
    turn = ready.post(_api(sid, "/say"), json={"content": "인구는?"}).json()
    ids = [str(p["id"]) for p in state["personas"]]
    assert _stored(turn) == {90}
    assert turn["agreement"]["understanding"] == {i: 90 for i in ids}
    assert turn["agreement"]["all_agreed"] is True


@pytest.mark.parametrize("artifact, expected", [("", 79), ("3/4", 79)])
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
        _react(
            on_task=False,
            utterance=STATEMENT,
            misconception="분모끼리 더함",
            understanding=85,
        ),
    )
    assert _stored(turn) == {79}


# 같은 장면에서 앞서 낸 산출물을 그대로 들고 온 질문 반응 (#341)
ART = "2050년 예상 인구 그래프"
F3 = (
    "저... 중학교 수학에서 배운다는 말에 조금 걱정이 되는데, 우리가 엑셀이나 "
    "엔트리로 직접 그래프를 그리면서 이해하는 방법이 따로 있는 건가요?"
)


@pytest.mark.parametrize(
    "utterance, misconception, artifact",
    [
        (
            "분모끼리 더하면 돼요.",
            "어떻게 시작해야 할지 모름",
            "",
        ),  # 끝말 필터 (#302)
        ("잘 모르겠어요.", "분모끼리 더함", ""),  # 막힘뿐 (#330)
        (
            F3,
            "계산을 직접 해야 한다고 오해함",
            ART,
        ),  # 같은 산출물 + 질문 (#341)
    ],
)
def test_off_task_cleared_misconception_keeps_previous(
    ready, fake_gemini, utterance, misconception, artifact
):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=60, artifact=artifact),
        _react(
            on_task=False,
            utterance=utterance,
            misconception=misconception,
            artifact=artifact,
            understanding=85,
        ),
    )
    assert _stored(turn) == {60}


def _misconceptions(turn):
    return {
        u["structured"]["misconception"]
        for u in turn["utterances"]
        if u["speaker_type"] == "student"
    }


@pytest.mark.parametrize(
    "first_artifact, utterance, artifact, kept",
    [
        (ART, F3, ART, ""),  # F3
        (
            ART,
            "저... 중학교 내용이라고 하니까 더 어렵게 느껴져요. "
            "2050년 미래를 예측하는 게 그렇게 복잡한 과정인가요?",
            ART,
            "",
        ),  # F6: live 24
        (
            ART,
            F3,
            "2040년 예상 인구 그래프",
            "계산을 직접 해야 한다고 오해함",
        ),  # K6
        (
            ART,
            "네, 분모끼리 더했어요.",
            ART,
            "계산을 직접 해야 한다고 오해함",
        ),  # K7
        ("", F3, ART, "계산을 직접 해야 한다고 오해함"),  # K8
        (ART, F3, "현우의 산출물: " + ART, ""),  # 접두어는 떼고 비교 (#350)
    ],
)
def test_same_artifact_question_has_no_misconception(
    ready, fake_gemini, first_artifact, utterance, artifact, kept
):
    """직전 자기 산출물을 그대로 들고 온 질문·막힘 반응은 오개념을 비운다 (#341)."""
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=60, artifact=first_artifact),
        _react(
            utterance=utterance,
            artifact=artifact,
            misconception="계산을 직접 해야 한다고 오해함",
            understanding=60,
        ),
    )
    assert _misconceptions(turn) == {kept}


def test_same_artifact_question_keeps_validator_cap(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=70, artifact=ART),
        _react(
            utterance=F3,
            artifact=ART,
            misconception="계산을 직접 해야 한다고 오해함",
            understanding=90,
        ),
    )
    assert _misconceptions(turn) == {""}
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


# --- 한 반응당 이해도 상승은 직전 값 + 20까지 (#310) ---


def test_on_task_rise_is_capped(ready, fake_gemini):
    state, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=30),
        _react(on_task=True, utterance=STATEMENT, understanding=82),
    )
    ids = [str(p["id"]) for p in state["personas"]]
    assert _stored(turn) == {50}
    assert turn["agreement"]["understanding"] == {i: 50 for i in ids}
    assert turn["agreement"]["agreed_persona_ids"] == []
    assert turn["agreement"]["all_agreed"] is False


@pytest.mark.parametrize("model, expected", [(60, 60), (61, 60)])
def test_rise_cap_boundary(ready, fake_gemini, model, expected):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=40),
        _react(utterance=STATEMENT, understanding=model),
    )
    assert _stored(turn) == {expected}


def test_rise_cap_applies_with_artifact(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=30),
        _react(understanding=85, artifact="행정구역 코드 삭제"),
    )
    assert _stored(turn) == {50}


def test_drop_is_not_capped(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=70),
        _react(
            on_task=True,
            utterance=STATEMENT,
            misconception="분모끼리 더함",
            understanding=30,
        ),
    )
    assert _stored(turn) == {30}


def test_misconception_big_rise_is_capped(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=30),
        _react(
            utterance=STATEMENT, misconception="분모끼리 더함", understanding=95
        ),
    )
    assert _stored(turn) == {50}


def test_stepwise_rise_reaches_agree_and_latch_holds(ready, fake_gemini):
    state, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=30),
        lambda key: _fresh(_react(understanding=90)),
    )
    assert _stored(turn) == {50}
    turn = ready.post(
        _api(state["session"]["id"], "/say"), json={"content": "다음"}
    ).json()
    assert _stored(turn) == {70}
    assert turn["agreement"]["all_agreed"] is False
    sid = state["session"]["id"]
    turn = ready.post(_api(sid, "/say"), json={"content": "또"}).json()
    assert _stored(turn) == {90}
    assert turn["agreement"]["all_agreed"] is True

    fake_gemini.results["student"] = _react(understanding=40)
    turn = ready.post(_api(sid, "/say"), json={"content": "다시"}).json()
    ids = [str(p["id"]) for p in state["personas"]]
    assert turn["agreement"]["understanding"] == {i: 40 for i in ids}
    assert turn["agreement"]["all_agreed"] is True
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 200


def test_regenerated_reaction_rise_is_capped(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.results["student"] = _react(understanding=40)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": "인구는?"})

    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(
        on_task=True, utterance=STATEMENT, understanding=82
    )
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 60


# --- 교사 말 따라 하기·같은 산출물 짧게 다시 말하기는 이해도를 올리지 않는다 (#319) ---

ASK = (
    "그럼 우리가 확인하려는 건 뭘까? "
    "'어느 나이대 사람이 늘고 줄어드는지'라고 말해 볼 수 있을까?"
)
ECHO = "어... 어느 나이대 사람이 늘고 줄어드는지요?"
OWN = "어... 줄어들 것 같아요. 애들이... 잘 안 태어나서요?"
SAVED = "네, 저도 저장했어요..."
XLSX = "인구구성비_모둠이름.xlsx"


def test_core_strips_fillers_punctuation_and_final_yo():
    core = session_service._core
    assert core(ECHO) == "어느나이대사람이늘고줄어드는지"
    assert core(SAVED) == "저도저장했어"
    assert len(core(OWN)) == 16


def test_echo_of_teacher_is_held(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=50),
        _react(utterance=ECHO, understanding=70),
        content=ASK,
    )
    assert _stored(turn) == {50}


def test_echo_drop_is_kept(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=50),
        _react(utterance=ECHO, understanding=30),
        content=ASK,
    )
    assert _stored(turn) == {30}


def test_own_words_with_same_artifact_rise(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=50, artifact=XLSX),
        _react(utterance=OWN, understanding=70, artifact=XLSX),
        content=ASK,
    )
    assert _stored(turn) == {70}


@pytest.mark.parametrize(
    "first, then, expected",
    [
        (XLSX, XLSX, 60),
        ("a.xlsx", "b.xlsx", 80),
        ("", "", 80),
        (XLSX, "산출물: " + XLSX, 60),  # 접두어는 떼고 비교 (#350)
    ],
)
def test_same_artifact_short_reaction_is_held(
    ready, fake_gemini, first, then, expected
):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=60, artifact=first),
        _react(utterance=SAVED, understanding=80, artifact=then),
    )
    assert _stored(turn) == {expected}


def test_short_echo_rises(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=50),
        _react(utterance="65세 이상이요", understanding=70),
        content="65세 이상은 몇 명일까?",
    )
    assert _stored(turn) == {70}


@pytest.mark.parametrize(
    "utterance, expected",
    [("일이삼사오육칠팔구", 70), ("일이삼사오육칠팔구십", 50)],
)
def test_echo_length_boundary(ready, fake_gemini, utterance, expected):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=50),
        _react(utterance=utterance, understanding=70),
        content="일이삼사오육칠팔구십 하나",
    )
    assert _stored(turn) == {expected}


@pytest.mark.parametrize(
    "utterance, expected",
    [("일이삼사오육칠팔구십", 50), ("일이삼사오육칠팔구십일", 70)],
)
def test_same_artifact_length_boundary(ready, fake_gemini, utterance, expected):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=50, artifact=XLSX),
        _react(utterance=utterance, understanding=70, artifact=XLSX),
    )
    assert _stored(turn) == {expected}


def test_regenerated_echo_is_held(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.results["student"] = _react(understanding=40)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": ASK})

    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance=ECHO, understanding=60)
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 40


# --- 따옴표로 알려 준 답에 짧은 꼬리만 붙인 반응도 이해도를 올리지 않는다 (#332) ---

QUOTED_ASK = (
    "맞아! 그럼 우리가 이 파일로 앞으로 확인하려는 건 뭘까? "
    "'어느 나이대 사람이 늘고 줄어드는지'라고 말해 볼 수 있을까?"
)
TAILED = "어... 어느 나이대 사람이 늘고 줄어드는지... 보는 거요."


def _say_after_60(
    client, fake_gemini, utterance, understanding=80, content=QUOTED_ASK
):
    _, turn = _enter_then_say(
        client,
        fake_gemini,
        _react(understanding=60),
        _react(utterance=utterance, understanding=understanding),
        content=content,
    )
    return _stored(turn)


def test_quoted_echo_with_short_tail_is_held(ready, fake_gemini):
    assert _say_after_60(ready, fake_gemini, TAILED) == {60}


def test_quoted_echo_with_tail_drop_is_kept(ready, fake_gemini):
    assert _say_after_60(ready, fake_gemini, TAILED, understanding=40) == {40}


@pytest.mark.parametrize(
    "tail, expected", [("일이삼사오요", 60), ("일이삼사오육요", 80)]
)
def test_quoted_echo_tail_boundary(ready, fake_gemini, tail, expected):
    utterance = f"어느 나이대 사람이 늘고 줄어드는지 {tail}"
    assert _say_after_60(ready, fake_gemini, utterance) == {expected}


def test_short_quoted_span_with_tail_rises(ready, fake_gemini):
    stored = _say_after_60(
        ready,
        fake_gemini,
        "인구구성비_모둠이름 했어요",
        content="'인구구성비_모둠이름'으로 저장해 볼까?",
    )
    assert stored == {80}


def test_unquoted_teacher_echo_with_tail_is_held(ready, fake_gemini):
    # 따옴표가 없어도 교사 말을 거의 그대로 되풀이하면 오르지 않는다 (#366)
    unquoted = QUOTED_ASK.replace("'", "")
    assert _say_after_60(ready, fake_gemini, TAILED, content=unquoted) == {60}


def test_quoted_phrase_with_own_words_rises(ready, fake_gemini):
    own = "어느 나이대 사람이 늘고 줄어드는지 보면 아기가 줄어드는 걸 알 수 있어요"
    assert _say_after_60(ready, fake_gemini, own) == {80}


@pytest.mark.parametrize(
    "open_, close", [("'", "'"), ('"', '"'), ("‘", "’"), ("“", "”")]
)
def test_quote_styles_are_all_matched(ready, fake_gemini, open_, close):
    content = QUOTED_ASK.replace("'", open_, 1).replace("'", close, 1)
    assert _say_after_60(ready, fake_gemini, TAILED, content=content) == {60}


def test_mismatched_quote_styles_echo_is_held_as_unquoted(ready, fake_gemini):
    # 짝이 안 맞는 따옴표는 구간이 아니지만 따옴표 밖 따라 하기로 걸린다 (#366)
    content = QUOTED_ASK.replace("지'라고", '지"라고')
    assert _say_after_60(ready, fake_gemini, TAILED, content=content) == {60}


def test_word_internal_apostrophe_does_not_open_a_span(ready, fake_gemini):
    content = "It's your turn. '어느 나이대 사람이 늘고 줄어드는지'라고 말해 봐"
    assert _say_after_60(ready, fake_gemini, TAILED, content=content) == {60}


def test_nested_span_of_other_style_is_matched(ready, fake_gemini):
    content = (
        "'먼저 \"어느 나이대 사람이 늘고 줄어드는지\"를 확인해요'라고 말해 봐"
    )
    utterance = "어느 나이대 사람이 늘고 줄어드는지 보는 거요"
    assert _say_after_60(ready, fake_gemini, utterance, content=content) == {60}


# 따옴표 문구 일부를 어미만 바꿔 따라 한 반응 (#337, 실세션 #13 seq 38·39)
SEOYUN_ASK = (
    "서윤아, '노인 비율이 커져도 전체 사람 수가 늘어나는 건 아니다'라고 "
    "말해 볼 수 있을까?"
)


def test_partial_quoted_echo_with_changed_ending_is_held(ready, fake_gemini):
    utterance = "전체 사람 수가... 늘어나는 건... 아닌가 봐요..."
    assert _say_after_60(ready, fake_gemini, utterance, content=SEOYUN_ASK) == {
        60
    }


def test_partial_quoted_echo_drop_is_kept(ready, fake_gemini):
    utterance = "전체 사람 수가... 늘어나는 건... 아닌가 봐요..."
    stored = _say_after_60(
        ready, fake_gemini, utterance, understanding=40, content=SEOYUN_ASK
    )
    assert stored == {40}


# 공통 부분 '전체사람수가늘어나는건아'(12자) 뒤 나머지 5자는 유지, 6자는 오른다
@pytest.mark.parametrize(
    "tail, expected", [("일이삼사요", 60), ("일이삼사오요", 80)]
)
def test_partial_quoted_echo_remainder_boundary(
    ready, fake_gemini, tail, expected
):
    utterance = f"전체 사람 수가 늘어나는 건 아닌 {tail}"
    stored = _say_after_60(ready, fake_gemini, utterance, content=SEOYUN_ASK)
    assert stored == {expected}


def test_partial_quoted_overlap_below_min_rises(ready, fake_gemini):
    # 공통 부분 '사람수가늘어나는건' 9자, 나머지 1자
    stored = _say_after_60(
        ready, fake_gemini, "사람 수가 늘어나는 건가요", content=SEOYUN_ASK
    )
    assert stored == {80}


def test_unquoted_instruction_paraphrase_rises(ready, fake_gemini):
    content = (
        "서준아, 선생님 말을 그대로 따라 해 볼래? 장래인구추계 파일에서 "
        "연도와 나이대별 비율 열만 남기고 나머지는 지운다."
    )
    utterance = "네, 연도와 나이대별 비율 열만 남기고 다 지우면 되는 거죠? 바로 해 볼게요!"
    assert _say_after_60(ready, fake_gemini, utterance, content=content) == {80}


def test_learning_goal_restatement_rises(ready, fake_gemini):
    content = (
        "오늘은 '우리나라 인구 구성비가 앞으로 어떻게 바뀔지 데이터로 예측하고, "
        "우리 교실에 생길 변화를 생각해 보기'를 공부할 거예요. "
        "오늘 공부할 내용을 짝에게 한 문장으로 말해 볼까요?"
    )
    # 공통 41자, 나머지 11자 ('오늘공부할내용은' + '는거야')
    utterance = (
        "오늘 공부할 내용은 우리나라 인구 구성비가 앞으로 어떻게 바뀔지 데이터로 "
        "예측하고, 우리 교실에 생길 변화를 생각해 보는 거야."
    )
    assert _say_after_60(ready, fake_gemini, utterance, content=content) == {80}


# --- 따옴표 없는 교사 설명을 말을 조금 빼고 어미만 바꿔 따라 해도 오르지 않는다 (#366) ---

# 실세션 #20 seq 19 교사 말과 seq 20·21·22 학생 말
FOOT_ASK = (
    "소율이와 예은이도 목표를 잘 잡았어요! 우리가 사람들의 발 크기 자료를 직접 "
    "하나하나 다 재려면 시간이 오래 걸리니까, 이미 조사된 공공데이터를 가져와서 "
    "활용하는 거예요. 자, 그럼 오늘 첫 번째 활동으로 들어가기 전에, 왜 공공데이터를 "
    "쓰는지와 우리가 만들 프로그램이 무엇인지 각자 정리해서 이야기해 볼까요?"
)
MINJUN = (
    "우리가 직접 다 재려면 시간이 너무 오래 걸리니까, 이미 조사되어 있는 "
    "공공데이터를 가져와서 효율적으로 프로그램을 만들 수 있어요."
)
GEONWOO = (
    "우리가 직접 다 재려면 시간이 너무 오래 걸리니까, 이미 조사된 공공데이터를 "
    "가져와서 편하게 쓰려고요!"
)
SOYUL = "우리가 직접 다 재려면 시간이 오래 걸려서 이미 조사된 공공데이터를 가져와서 쓰는 것 같아요."


@pytest.mark.parametrize(
    "utterance", [MINJUN, GEONWOO, SOYUL], ids=["seq20", "seq21", "seq22"]
)
def test_unquoted_explanation_echo_is_held(ready, fake_gemini, utterance):
    assert _say_after_60(ready, fake_gemini, utterance, content=FOOT_ASK) == {
        60
    }


def test_unquoted_explanation_echo_drop_is_kept(ready, fake_gemini):
    stored = _say_after_60(
        ready, fake_gemini, SOYUL, understanding=40, content=FOOT_ASK
    )
    assert stored == {40}


def test_unquoted_explanation_echo_with_new_artifact_rises(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(understanding=60),
        _react(utterance=SOYUL, understanding=80, artifact=XLSX),
        content=FOOT_ASK,
    )
    assert _stored(turn) == {80}


def test_short_unquoted_paraphrase_rises(ready, fake_gemini):
    # 실세션 #20 seq 23
    stored = _say_after_60(
        ready, fake_gemini, "직접 다 재기 어려우니까요…?", content=FOOT_ASK
    )
    assert stored == {80}


def test_own_answer_reusing_unquoted_words_rises(ready, fake_gemini):
    # 실세션 #18 seq 89·91: 교사 말을 받아 자기 판단을 말한 반응
    content = (
        "여러분, 자료실의 꺾은선그래프를 보세요. 유소년 비율 선이 계속 아래로 "
        "내려가 있어요. 그래프의 이 선 하나만 보면, 우리나라 전체 인구 수도 같이 "
        "줄어들고 있다는 것을 알 수 있을까요? 확실하지 않으면 솔직하게 말해도 "
        "됩니다. 각자 네 생각을 한 문장으로 말해 보세요."
    )
    utterance = (
        "유소년 비율 선이 내려간다고 해서 전체 인구 수도 같이 줄어들고 있다고 "
        "바로 알기는 어려울 것 같습니다."
    )
    assert _say_after_60(ready, fake_gemini, utterance, content=content) == {80}


def test_regenerated_unquoted_explanation_echo_is_held(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.results["student"] = _react(understanding=60)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": FOOT_ASK})

    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance=SOYUL, understanding=80)
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 60


def test_regenerated_quoted_echo_with_tail_is_held(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.results["student"] = _react(understanding=60)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": QUOTED_ASK})

    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance=TAILED, understanding=80)
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 60


# --- 자기 직전 말을 되풀이한 반응은 이해도를 올리지 않는다 (#336) ---

# 교사 말에 학생 문장이 없어 규칙 A·A′로는 설명되지 않는다
REPEAT_ASK = "좋아. 방금 말한 거 한 번만 더 짧게 말해 줄래?"
SAID = "전체 인구 중에서 각 나이대가 차지하는 비율이요."


def _repeat_after_20(
    client,
    fake_gemini,
    utterance,
    understanding=35,
    before=SAID,
    artifacts=("", ""),
):
    _, turn = _enter_then_say(
        client,
        fake_gemini,
        _react(utterance=before, understanding=20, artifact=artifacts[0]),
        _react(
            utterance=utterance,
            understanding=understanding,
            artifact=artifacts[1],
        ),
        content=REPEAT_ASK,
    )
    return _stored(turn)


def test_own_repeat_without_artifact_is_held(ready, fake_gemini):
    assert _repeat_after_20(ready, fake_gemini, SAID[:-1] + "...") == {20}


def test_own_repeat_shortened_is_held(ready, fake_gemini):
    assert _repeat_after_20(
        ready, fake_gemini, "각 나이대가 차지하는 비율이요."
    ) == {20}


def test_own_repeat_with_added_content_rises(ready, fake_gemini):
    more = SAID + " 그래서 65세 이상이 늘면 그 비율이 커져요."
    assert _repeat_after_20(ready, fake_gemini, more) == {35}


@pytest.mark.parametrize(
    "utterance, expected",
    [("일이삼사오육칠팔구", 35), ("일이삼사오육칠팔구십", 20)],
)
def test_own_repeat_length_boundary(ready, fake_gemini, utterance, expected):
    stored = _repeat_after_20(
        ready, fake_gemini, utterance, before="일이삼사오육칠팔구십 하나요"
    )
    assert stored == {expected}


@pytest.mark.parametrize(
    "artifacts, expected",
    [(("", XLSX), 35), (("a.xlsx", "b.xlsx"), 35), ((XLSX, XLSX), 20)],
)
def test_own_repeat_artifact(ready, fake_gemini, artifacts, expected):
    stored = _repeat_after_20(ready, fake_gemini, SAID, artifacts=artifacts)
    assert stored == {expected}


def test_own_repeat_drop_is_kept(ready, fake_gemini):
    assert _repeat_after_20(ready, fake_gemini, SAID, understanding=10) == {10}


def test_own_repeat_without_previous_valid_reaction_rises(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    fake_gemini.parse_fail.add("student")
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance=SAID, understanding=35)
    turn = ready.post(_api(sid, "/say"), json={"content": REPEAT_ASK}).json()
    assert _stored(turn) == {35}


def test_other_students_repeat_is_not_held(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    speaker = str(state["personas"][0]["source_record_id"])
    fake_gemini.results["student"] = lambda key: _react(
        utterance=SAID if key == speaker else "잘 모르겠어요.", understanding=20
    )
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.results["student"] = _react(utterance=SAID, understanding=35)
    turn = ready.post(_api(sid, "/say"), json={"content": REPEAT_ASK}).json()
    by_persona = {
        u["persona_id"]: u["structured"]["understanding"]
        for u in turn["utterances"]
        if u["speaker_type"] == "student"
    }
    speaker_id = state["personas"][0]["id"]
    assert by_persona.pop(speaker_id) == 20
    assert set(by_persona.values()) == {35}


def test_regenerated_own_repeat_is_held(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.results["student"] = _react(utterance=SAID, understanding=20)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": REPEAT_ASK})

    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(
        utterance=SAID[:-1] + "...", understanding=35
    )
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 20


# --- 새 산출물 없는 맞장구·같은 말 되풀이는 이해도를 올리지 않는다 (#352) ---

STUCK12 = "얼마 차이나는지 잘 모르겠어요."  # core 12자: #319 같은 산출물 기준(10자) 밖


@pytest.mark.parametrize(
    "utterance",
    [
        "네...",
        "네!",
        "",
        "네, 알겠습니다.",
        "아, 알겠어요!",
        "네, 알겠어요, 선생님.",
        "네 선생님",
        "알겠어요 쌤",
    ],
)
def test_ack_only_reaction_is_held(ready, fake_gemini, utterance):
    assert _repeat_after_20(ready, fake_gemini, utterance) == {20}


def test_identical_stuck_repeat_is_held(ready, fake_gemini):
    assert _repeat_after_20(
        ready, fake_gemini, "잘 모르겠어요.", before="잘 모르겠어요."
    ) == {20}


def test_identical_short_repeat_is_held(ready, fake_gemini):
    # core가 둘 다 "12"라 #336의 10자 기준 밖이다
    assert _repeat_after_20(ready, fake_gemini, "네, 12요.", before="12요") == {
        20
    }


@pytest.mark.parametrize(
    "before, utterance", [("1.2요", "12요"), ("3.5퍼센트요", "35퍼센트요")]
)
def test_corrected_number_rises(ready, fake_gemini, before, utterance):
    # _core는 소수점을 떼어 core가 같지만 수치를 고친 답이다
    assert _repeat_after_20(ready, fake_gemini, utterance, before=before) == {
        35
    }


@pytest.mark.parametrize(
    "before, utterance",
    [("1,000명이요", "1000명이요"), ("1234명이요", "1,234명이요")],
)
def test_thousands_separator_repeat_is_held(
    ready, fake_gemini, before, utterance
):
    # 천 단위 쉼표만 다른 같은 수는 되풀이다
    assert _repeat_after_20(ready, fake_gemini, utterance, before=before) == {
        20
    }


@pytest.mark.parametrize(
    "utterance",
    [
        "아니요, 신어보고 골랐어요.",
        "공부를 많이 해서요…?",
        "잘... " + STUCK12,
        "잘 모르겠지만 한 삼 센티미터 정도 차이 나는 것 같아요.",
        "네, 알겠어요. 자로 재 볼게요.",
        "13이요",
        "잘 모르겠지만 3cm 같아요.",
        "모르겠는데 5센티요",
        "몰라요, 그냥 큰 거요",
        "3cm 같아요. 헷갈려요.",
        "스물일곱 명이요… 잘 모르겠어요.",
        "모르겠어요. 자로 재면 되나요?",
        "아니요, 잘 모르겠어요.",
        "얼마나 더 큰지는 잘 모르겠어요.",
        "잘은 모르겠고 3cm 같아요.",
        "헷갈려서 3cm로 썼어요.",
        "정확히는 몰라도 3cm 같아요.",
    ],
)
def test_reaction_with_content_rises(ready, fake_gemini, utterance):
    assert _repeat_after_20(ready, fake_gemini, utterance, before="12요") == {
        35
    }


@pytest.mark.parametrize(
    "utterance, artifacts, expected",
    [
        (STUCK12, ("", XLSX), 35),
        (STUCK12, ("a.xlsx", "b.xlsx"), 35),
        ("네...", (XLSX, XLSX), 20),
        ("네...", ("", XLSX), 35),
        ("12요", ("", XLSX), 35),
        ("잘 모르겠어요.", ("", XLSX), 35),
        ("잘 모르겠어요.", ("a.xlsx", "b.xlsx"), 35),
    ],
)
def test_no_new_showing_artifact(
    ready, fake_gemini, utterance, artifacts, expected
):
    stored = _repeat_after_20(
        ready, fake_gemini, utterance, before="12요", artifacts=artifacts
    )
    assert stored == {expected}


def test_no_new_showing_drop_is_kept(ready, fake_gemini):
    assert _repeat_after_20(ready, fake_gemini, "네...", understanding=10) == {
        10
    }


def test_first_reaction_ack_is_not_held(ready, fake_gemini):
    fake_gemini.results["student"] = _react(utterance="네...", understanding=60)
    state = _create(ready)
    turn = ready.post(_api(state["session"]["id"], "/phases/0/enter")).json()
    assert set(turn["agreement"]["understanding"].values()) == {60}


def test_ack_without_previous_valid_reaction_rises(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    fake_gemini.parse_fail.add("student")
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance="네...", understanding=35)
    turn = ready.post(_api(sid, "/say"), json={"content": REPEAT_ASK}).json()
    assert _stored(turn) == {35}


def test_off_task_ack_keeps_previous(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(utterance=SAID, understanding=20),
        _react(on_task=False, utterance="네...", understanding=10),
    )
    assert _stored(turn) == {20}


def test_regenerated_ack_is_held(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.results["student"] = _react(utterance=SAID, understanding=20)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": REPEAT_ASK})

    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance="네...", understanding=35)
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 20


def test_ack_only_never_reaches_agree(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(utterance=SAID, understanding=70),
        _react(utterance="네, 알겠습니다.", understanding=90),
    )
    assert _stored(turn) == {70}
    assert turn["agreement"]["all_agreed"] is False


def test_vocative_ack_never_reaches_agree(ready, fake_gemini):
    _, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(utterance=SAID, understanding=70),
        _react(utterance="네, 알겠어요, 선생님.", understanding=90),
    )
    assert _stored(turn) == {70}
    assert turn["agreement"]["all_agreed"] is False


# --- '모르겠어요'뿐인 반응은 닫힌 목록으로 이해도를 올리지 않는다 (#353) ---

STUCK = "잘 모르겠어요."


@pytest.mark.parametrize(
    "utterance",
    [
        "잘… 모르겠어요.",
        "모르겠어요...",
        "몰라요.",
        "잘… 잘 몰라요.",
        "네, 잘 모르겠어요.",
        "글쎄요... 잘 모르겠어요.",
        "잘 모르겠어요...",
        # 기록에서 본 형태 (#357)
        "그냥 잘 모르겠어요.",
        "너무 어려워서 잘 모르겠어요...",
        "모르겠어요, 너무 어려워요.",
        "갑자기 어려운 말이 나와서 잘 모르겠어요.",
        "갑자기 너무 어려워져서 잘 모르겠어요.",
        "무슨 말씀이신지 잘 모르겠어요...",
        "저기요, 무슨 말씀이신지 잘 모르겠어요.",
        "글쎄요... 정확히는 잘 모르겠어요...",
        "잘... 잘 모르겠어요.",
        "혼자서는 잘 모르겠어요.",
        "어떻게 하는지 잘 모르겠어요.",
        "어떻게 해야 되는지 잘 모르겠어요.",
    ],
)
def test_stuck_only_reaction_is_held(ready, fake_gemini, utterance):
    assert _repeat_after_20(ready, fake_gemini, utterance, before="12요") == {
        20
    }


@pytest.mark.parametrize(
    "utterance",
    [
        "잘 모르겠는데… 조금 더 크신 것 같아요.",
        "글쎄요... 한 스물여덟... 아니요, 잘 모르겠어요.",
        "피자요...? 잘 모르겠어요.",
        "아니요, 잘 몰라서 그냥 신어보고 샀어요.",
        "잘... 모르겠어요. 연습해서요.",
        "아니요, 잘 몰라요.",
    ],
)
def test_stuck_with_content_still_rises(ready, fake_gemini, utterance):
    assert _repeat_after_20(ready, fake_gemini, utterance, before="12요") == {
        35
    }


def test_listed_stuck_with_new_artifact_rises(ready, fake_gemini):
    stored = _repeat_after_20(
        ready,
        fake_gemini,
        "혼자서는 잘 모르겠어요.",
        before="12요",
        artifacts=("", "표 초안"),
    )
    assert stored == {35}


def test_stuck_only_drop_is_kept(ready, fake_gemini):
    stored = _repeat_after_20(
        ready, fake_gemini, STUCK, understanding=10, before="12요"
    )
    assert stored == {10}


def test_first_reaction_stuck_only_is_not_held(ready, fake_gemini):
    fake_gemini.results["student"] = _react(utterance=STUCK, understanding=60)
    state = _create(ready)
    turn = ready.post(_api(state["session"]["id"], "/phases/0/enter")).json()
    assert set(turn["agreement"]["understanding"].values()) == {60}


def test_stuck_only_without_previous_valid_reaction_rises(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    fake_gemini.parse_fail.add("student")
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance=STUCK, understanding=35)
    turn = ready.post(_api(sid, "/say"), json={"content": REPEAT_ASK}).json()
    assert _stored(turn) == {35}


def test_regenerated_stuck_only_is_held(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.results["student"] = _react(utterance=SAID, understanding=20)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": REPEAT_ASK})

    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance=STUCK, understanding=35)
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [fixed] = r.json()["utterances"]
    assert fixed["structured"]["understanding"] == 20


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


def _flow_session(client):
    """과업이 있는 3장면 세션 (#316)."""
    cands = client.get(
        "/api/simulation/candidates",
        params={"n": 4, "seed": 7, "level": "High"},
    ).json()["candidates"]
    body = {
        "personas": [
            {"ref": c["ref"], "pseudonym": c["pseudonym"]} for c in cands
        ],
        "phases": [
            {
                "name": "도입",
                "teacher_prompt": "발문 0",
                "task": "인구 그래프 읽기",
            },
            {
                "name": "활동1",
                "teacher_prompt": "발문 1",
                "task": "구성비 예측",
            },
            {"name": "정리", "teacher_prompt": "발문 2"},
        ],
    }
    r = client.post("/api/simulation/sessions", json=body)
    assert r.status_code == 201
    return r.json()


def _block(user, header):
    """header 다음 줄부터 빈 줄이나 다음 [..] 머리줄 전까지."""
    lines = user.splitlines()
    if header not in lines:
        return None
    out = []
    for ln in lines[lines.index(header) + 1 :]:
        if not ln or ln.startswith("["):
            break
        out.append(ln)
    return out


def _recording(fake_gemini, monkeypatch):
    prompts = {}

    def recording(kind, **kw):
        if kind == "student":
            prompts[kw["persona_key"]] = kw["user"]
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    return prompts


def test_student_call_scene0_has_lesson_flow_only(
    ready, fake_gemini, monkeypatch
):
    prompts = _recording(fake_gemini, monkeypatch)
    state = _flow_session(ready)
    ready.post(_api(state["session"]["id"], "/phases/0/enter"))
    assert len(prompts) == 4
    for u in prompts.values():
        assert _block(u, "[수업 흐름]") == [
            "1. 도입 — 인구 그래프 읽기 / 교사 발문: 발문 0 (지금)",
            "2. 활동1 — 구성비 예측 / 교사 발문: 발문 1",
            "3. 정리 — (없음) / 교사 발문: 발문 2",
        ]
        assert "[이전 장면에서 내가 보인 것]" not in u
        assert (
            u.index("자료:")
            < u.index("[수업 흐름]")
            < u.index("[이번 장면 대화]")
        )


def _scene1_with_history(ready, fake_gemini):
    """장면 0에서 학생마다 다른 산출물을 남기고 장면 1로 넘긴다.

    keys[0]: 마지막 반응의 산출물이 비어 그 전 산출물, keys[3]: 산출물 없음 → 마지막 발화.
    """
    state = _flow_session(ready)
    sid = state["session"]["id"]
    keys = [str(p["source_record_id"]) for p in state["personas"]]
    fake_gemini.results["student"] = lambda k: _react(
        utterance=f"말0-{k}", artifact="" if k == keys[3] else f"A0-{k}"
    )
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.results["student"] = lambda k: _react(
        utterance=f"말1-{k}",
        artifact="" if k in (keys[0], keys[3]) else f"A1-{k}",
    )
    ready.post(_api(sid, "/say"), json={"content": "다 했니?"})
    r = ready.post(_api(sid, "/advance"), json={"mode": "skip"})
    assert r.json()["current_phase_idx"] == 1
    fake_gemini.results["student"] = lambda k: _react(utterance=f"새-{k}")
    ready.post(_api(sid, "/phases/1/enter"))
    expected = {
        keys[0]: f"1. 도입: A0-{keys[0]}",
        keys[1]: f"1. 도입: A1-{keys[1]}",
        keys[2]: f"1. 도입: A1-{keys[2]}",
        keys[3]: f"1. 도입: 말1-{keys[3]}",
    }
    return state, keys, expected


def _assert_history(u, k, keys, expected):
    assert _block(u, "[이전 장면에서 내가 보인 것]") == [expected[k]]
    for other in keys:
        if other != k:
            assert (
                f"0-{other}" not in u
                and f"1-{other}" not in u.split("[이번 장면 대화]")[0]
            )
    assert _block(u, "[수업 흐름]") == [
        "1. 도입 — 인구 그래프 읽기 / 교사 발문: 발문 0",
        "2. 활동1 — 구성비 예측 / 교사 발문: 발문 1 (지금)",
        "3. 정리 — (없음) / 교사 발문: 발문 2",
    ]
    after = "[직전 이해도]" if "[직전 이해도]" in u else "[이번 장면 대화]"
    assert u.index("[이전 장면에서 내가 보인 것]") < u.index(after)


def test_student_call_scene1_say_sees_own_previous_scene(
    ready, fake_gemini, monkeypatch
):
    prompts = _recording(fake_gemini, monkeypatch)
    state, keys, expected = _scene1_with_history(ready, fake_gemini)
    assert prompts.keys() == set(keys)  # 장면 1 진입 호출
    for k, u in prompts.items():
        _assert_history(u, k, keys, expected)
    prompts.clear()
    sid = state["session"]["id"]
    ready.post(_api(sid, "/say"), json={"content": "예측해 볼까?"})
    assert prompts.keys() == set(keys)
    for k, u in prompts.items():
        _assert_history(u, k, keys, expected)
        talk = u.split("[이번 장면 대화]\n", 1)[1]
        assert "발문 0" not in talk and "다 했니?" not in talk
        assert "말0-" not in talk and "말1-" not in talk


def test_student_call_regenerate_sees_own_previous_scene(
    ready, fake_gemini, monkeypatch
):
    prompts = _recording(fake_gemini, monkeypatch)
    state, keys, expected = _scene1_with_history(ready, fake_gemini)
    sid = state["session"]["id"]
    persona = state["personas"][3]
    fake_gemini.parse_fail.add(keys[3])
    ready.post(_api(sid, "/say"), json={"content": "예측해 볼까?"})
    fake_gemini.parse_fail.clear()
    prompts.clear()
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [(k, u)] = prompts.items()
    assert k == keys[3]
    _assert_history(u, k, keys, expected)
    assert "not json" not in u  # 실패한 그 행의 원문


def _row(phase_idx, content, artifact=None, persona_id=1, failed=False):
    from types import SimpleNamespace

    structured = None if failed else {"artifact": artifact or ""}
    return SimpleNamespace(
        phase_idx=phase_idx,
        speaker_type="student",
        persona_id=persona_id,
        content=content,
        structured=structured,
    )


def test_shown_before_ignores_whitespace_artifacts():
    shown = session_service._shown_before
    assert shown(1, 1, [_row(0, "말A", "답"), _row(0, "말B", "   ")]) == {
        0: "답"
    }
    assert shown(1, 1, [_row(0, "말A", " \n"), _row(0, "말B", "  ")]) == {
        0: "말B"
    }
    assert shown(1, 1, [_row(0, "말A", "  답 ")]) == {0: "답"}


def test_shown_before_ignores_parse_failed_rows():
    shown = session_service._shown_before
    history = [_row(0, "말A"), _row(0, "{raw model text", failed=True)]
    assert shown(1, 1, history) == {0: "말A"}
    assert shown(1, 1, [_row(0, "{raw model text", failed=True)]) == {}


def test_student_call_scene2_lists_each_previous_phase_by_number():
    from types import SimpleNamespace

    phases = [
        SimpleNamespace(
            idx=i, name=n, task=t, materials="", minutes=None, teacher_prompt=""
        )
        for i, (n, t) in enumerate(
            [("도입", "인구 그래프 읽기"), ("활동1", ""), ("활동2", "")]
        )
    ]
    persona = SimpleNamespace(
        id=1,
        display_name="준서",
        raw_profile={},
        adapted_level="High",
        adapted_profile={},
        source="dataset",
        source_record_id=7,
    )
    history = [
        _row(0, "말0", "답0"),
        _row(0, "남의 말", "남의 답", persona_id=2),
        _row(1, "남의 말1", "남의 답1", persona_id=2),
        _row(2, "지금 말", "지금 답"),
    ]
    user = session_service.student_call(
        persona, phases[2], [], phases=phases, history=history
    )["user"]
    assert _block(user, "[이전 장면에서 내가 보인 것]") == ["1. 도입: 답0"]
    # 발문이 빈 장면은 " / 교사 발문:"을 붙이지 않는다 (#367)
    assert _block(user, "[수업 흐름]") == [
        "1. 도입 — 인구 그래프 읽기",
        "2. 활동1 — (없음)",
        "3. 활동2 — (없음) (지금)",
    ]

    history.insert(2, _row(1, "말1", "답1"))
    user = session_service.student_call(
        persona, phases[2], [], phases=phases, history=history
    )["user"]
    assert _block(user, "[이전 장면에서 내가 보인 것]") == [
        "1. 도입: 답0",
        "2. 활동1: 답1",
    ]

    history = [_row(0, "{raw", failed=True), _row(1, "말1", "  ")]
    user = session_service.student_call(
        persona, phases[2], [], phases=phases, history=history
    )["user"]
    assert _block(user, "[이전 장면에서 내가 보인 것]") == ["2. 활동1: 말1"]
    assert "{raw" not in user

    history = [_row(0, "{raw", failed=True)]
    user = session_service.student_call(
        persona, phases[2], [], phases=phases, history=history
    )["user"]
    assert "[이전 장면에서 내가 보인 것]" not in user


def test_student_call_profile_has_gender(ready, fake_gemini, monkeypatch):
    import json

    from app.services.simulation.persona_pool import GENDER_LABEL

    systems = {}

    def recording(kind, **kw):
        if kind == "student":
            systems[kw["persona_key"]] = kw["system"]
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    state = _create(ready)
    ready.post(_api(state["session"]["id"], "/phases/0/enter"))
    assert len(systems) == 4
    for p in state["personas"]:
        system = systems[str(p["source_record_id"])]
        profile = json.loads(system.split("[나의 프로필]\n", 1)[1])
        assert list(profile)[:3] == ["가명", "학년", "성별"]
        assert profile["성별"] in GENDER_LABEL.values()


# --- 후속 턴 안내문은 마지막 교사 줄 바로 뒤에 붙는다 (#353) ---


def test_follow_up_say_ends_with_turn_note(ready, fake_gemini, monkeypatch):
    prompts = _recording(fake_gemini, monkeypatch)
    state = _create(ready)
    sid = state["session"]["id"]
    ready.post(_api(sid, "/phases/0/enter"))
    prompts.clear()
    ready.post(_api(sid, "/say"), json={"content": "신발 한번 볼래?"})
    assert len(prompts) == 4
    for u in prompts.values():
        assert u.splitlines()[-2:] == [
            "교사(전체): 신발 한번 볼래?",
            session_service.TURN_NOTE,
        ]
        assert "[직전 이해도]" in u
        assert u.count("[이번 반응]") == 1


def test_targeted_follow_up_say_ends_with_turn_note(
    ready, fake_gemini, monkeypatch
):
    prompts = _recording(fake_gemini, monkeypatch)
    state = _create(ready)
    sid = state["session"]["id"]
    target = state["personas"][1]
    ready.post(_api(sid, "/phases/0/enter"))
    prompts.clear()
    ready.post(
        _api(sid, "/say"),
        json={"content": "너는?", "target_persona_id": target["id"]},
    )
    [u] = prompts.values()
    assert u.splitlines()[-2:] == [
        f"교사({target['display_name']}에게): 너는?",
        session_service.TURN_NOTE,
    ]


def test_enter_phase_call_has_no_turn_note(ready, fake_gemini, monkeypatch):
    prompts = _recording(fake_gemini, monkeypatch)
    state = _create(ready)
    ready.post(_api(state["session"]["id"], "/phases/0/enter"))
    assert len(prompts) == 4
    for u in prompts.values():
        assert "[이번 반응]" not in u
        assert u.splitlines()[-1].startswith("교사(전체): ")


def test_regenerate_follow_up_has_turn_note(ready, fake_gemini, monkeypatch):
    prompts = _recording(fake_gemini, monkeypatch)
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": "어때?"})
    fake_gemini.parse_fail.clear()
    prompts.clear()
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [u] = prompts.values()
    assert u.splitlines()[-2:] == [
        "교사(전체): 어때?",
        session_service.TURN_NOTE,
    ]


def test_regenerate_first_reaction_has_no_turn_note(
    ready, fake_gemini, monkeypatch
):
    prompts = _recording(fake_gemini, monkeypatch)
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.clear()
    prompts.clear()
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    [u] = prompts.values()
    assert "[이번 반응]" not in u


# --- 다짐뿐인 후속 반응은 이해도를 올리지 않고 장면 동의로 친다 (#358) ---

PLEDGE = "네, 열심히 해 볼게요."
ENCOURAGE = "잘 할 수 있어. 자신감을 가지고"


def _pledge_turn(
    client,
    fake_gemini,
    utterance=PLEDGE,
    understanding=45,
    artifacts=("", ""),
    **kw,
):
    return _enter_then_say(
        client,
        fake_gemini,
        _react(utterance=SAID, understanding=40, artifact=artifacts[0]),
        _react(
            utterance=utterance,
            understanding=understanding,
            artifact=artifacts[1],
            **kw,
        ),
        content=ENCOURAGE,
    )


def _flags(turn):
    return {
        u["structured"].get("pledge")
        for u in turn["utterances"]
        if u["speaker_type"] == "student"
    }


def _ids(personas):
    return sorted(p["id"] for p in personas)


@pytest.mark.parametrize(
    "utterance",
    [
        PLEDGE,
        "네, 열심히 해볼게요.",
        "열심히 해 볼게요!",
        "열심히 할게요.",
        "네, 선생님. 열심히 해 볼게요.",
        "쌤, 저도 이제 열심히 배울게요.",
        "선생님, 저 열심히 할게요.",
        "앞으로 더 열심히 참여할게요.",
        "조금만 더 열심히 해 볼게요.",
        "최선을 다해 해 보겠습니다.",
        "꼭 노력해서 해 볼게요.",
        "힘내서 할게요.",
        "포기하지 않고 하겠습니다.",
        "잘 해 볼게요.",
        "잘할게요.",
        "노력할게요.",
        "노력해 볼게요.",
        "노력하겠습니다.",
        "최선을 다할게요.",
        "최선을 다하겠습니다.",
        "잘... 모르겠어요. 그냥 열심히 해볼게요.",
        "잘 모르겠어요. 열심히 할게요.",
        "몰라요. 그냥 잘 해 볼게요.",
        "어떻게 하는지 잘 모르겠어요. 그냥 노력해 볼게요.",
        "그냥 열심히 해 볼게요.",
    ],
)
def test_follow_up_pledge_is_held_and_agrees(ready, fake_gemini, utterance):
    state, turn = _pledge_turn(ready, fake_gemini, utterance)
    assert _stored(turn) == {40}
    assert _flags(turn) == {True}
    agreement = turn["agreement"]
    assert agreement["count"] == 4
    assert agreement["all_agreed"] is True
    assert sorted(agreement["pledged_persona_ids"]) == _ids(state["personas"])
    assert set(agreement["understanding"].values()) == {40}
    sid = state["session"]["id"]
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 200


def test_pledge_drop_is_kept(ready, fake_gemini):
    _, turn = _pledge_turn(ready, fake_gemini, understanding=30)
    assert _stored(turn) == {30}
    assert _flags(turn) == {True}


def test_off_task_pledge_keeps_previous_and_agrees(ready, fake_gemini):
    _, turn = _pledge_turn(ready, fake_gemini, understanding=10, on_task=False)
    assert _stored(turn) == {40}
    assert _flags(turn) == {True}


def test_pledge_with_same_carried_artifact_agrees(ready, fake_gemini):
    _, turn = _pledge_turn(ready, fake_gemini, artifacts=("a.xlsx", "a.xlsx"))
    assert _stored(turn) == {40}
    assert _flags(turn) == {True}


def test_first_reaction_pledge_is_not_consent(ready, fake_gemini):
    fake_gemini.results["student"] = _react(utterance=PLEDGE, understanding=60)
    state = _create(ready)
    turn = ready.post(_api(state["session"]["id"], "/phases/0/enter")).json()
    assert _flags(turn) == {None}
    assert turn["agreement"]["count"] == 0
    assert turn["agreement"]["pledged_persona_ids"] == []
    assert set(turn["agreement"]["understanding"].values()) == {60}


@pytest.mark.parametrize(
    "utterance",
    [
        "네, 자로 재어 볼게요.",
        "네… 재어 볼게요.",
        "네, 알겠어요. 자로 재 볼게요.",
        "네, 열심히 해 볼게요. 자로 재어 볼게요.",
        STUCK,
        "네, 알겠습니다.",
        "그냥 해 볼게요.",
        "네, 해 볼게요.",
        "잘 모르겠어요… 그냥 해볼게요.",
        "네, 엔트리 열고 데이터 불러오기 시작할게요.",
        "네, 알겠습니다. 일단 해보고 잘 안 되면 다시 여쭤볼게요.",
        "네… 잘 모르겠지만 재어 볼게요.",
        "네… 잘 알아보겠습니다.",
        "네… 잘 모르겠지만 잘 들어볼게요.",
        "네, 저도 아직 열을 지우는 중이에요. 조금만 더 해 볼게요.",
        "열심히... 해보는 거요.",
        "열심히 배우는 거요?",
        "열심히 해요.",
        "네, 선생님! 배추 생산량 데이터와 관련된 프로그램을 어떻게 만들지 기대돼요. 열심히 참여하겠습니다.",
        "잘 몰라요.",
        "그냥 잘 모르겠어요.",
    ],
)
def test_action_commitment_is_not_pledge(ready, fake_gemini, utterance):
    _, turn = _pledge_turn(ready, fake_gemini, utterance)
    assert _flags(turn) == {None}
    assert turn["agreement"]["count"] == 0
    assert turn["agreement"]["pledged_persona_ids"] == []


@pytest.mark.parametrize("artifacts", [("", "메모.txt"), ("a.xlsx", "b.xlsx")])
def test_pledge_with_new_artifact_is_not_consent(ready, fake_gemini, artifacts):
    _, turn = _pledge_turn(ready, fake_gemini, artifacts=artifacts)
    assert _flags(turn) == {None}
    assert turn["agreement"]["count"] == 0
    assert turn["agreement"]["pledged_persona_ids"] == []
    assert _stored(turn) == {45}


def test_pledge_with_misconception_is_not_consent(ready, fake_gemini):
    _, turn = _pledge_turn(ready, fake_gemini, misconception="분모끼리 더한다")
    assert _flags(turn) == {None}
    assert turn["agreement"]["count"] == 0
    assert turn["agreement"]["pledged_persona_ids"] == []
    assert _stored(turn) == {45}


def test_pledge_with_stuck_summary_misconception_agrees(ready, fake_gemini):
    # '…모른다' 오개념은 검증기가 비운다(#302) → 다짐 동의로 친다
    _, turn = _pledge_turn(
        ready, fake_gemini, misconception="무엇을 해야 할지 모른다"
    )
    assert _flags(turn) == {True}
    assert _stored(turn) == {40}


STUCK_PLEDGE = "잘 모르겠어요… 그냥 열심히 해 볼게요."


def _misconceptions(turn):
    return {
        u["structured"]["misconception"]
        for u in turn["utterances"]
        if u["speaker_type"] == "student"
    }


def test_stuck_pledge_with_cleared_misconception_is_not_consent(
    ready, fake_gemini
):
    # 말줄임으로 이은 막힘+다짐은 #330이 오개념을 비우지만 실제 오개념이 있었다 (#361 리뷰)
    state, turn = _pledge_turn(
        ready, fake_gemini, STUCK_PLEDGE, misconception="분모끼리 더한다"
    )
    assert _misconceptions(turn) == {""}
    assert _flags(turn) == {None}
    assert turn["agreement"]["count"] == 0
    assert turn["agreement"]["pledged_persona_ids"] == []
    assert _stored(turn) == {45}
    r = ready.post(
        _api(state["session"]["id"], "/advance"), json={"mode": "agree"}
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    "utterance", [STUCK_PLEDGE, "잘 모르겠어요. 그냥 열심히 해 볼게요."]
)
def test_stuck_pledge_with_carried_artifact_and_misconception_is_not_consent(
    ready, fake_gemini, utterance
):
    # 직전 산출물을 그대로 들면 #341 가드가 오개념을 비운다
    _, turn = _pledge_turn(
        ready,
        fake_gemini,
        utterance,
        artifacts=("a.xlsx", "a.xlsx"),
        misconception="분모끼리 더한다",
    )
    assert _flags(turn) == {None}
    assert turn["agreement"]["count"] == 0
    assert turn["agreement"]["pledged_persona_ids"] == []
    assert _stored(turn) == {45}


def test_stuck_pledge_with_stuck_summary_misconception_agrees(
    ready, fake_gemini
):
    _, turn = _pledge_turn(
        ready,
        fake_gemini,
        STUCK_PLEDGE,
        misconception="무엇을 해야 할지 모른다",
    )
    assert _misconceptions(turn) == {""}
    assert _flags(turn) == {True}
    assert _stored(turn) == {40}
    assert turn["agreement"]["count"] == 4


def test_pledge_without_previous_valid_reaction_is_not_consent(
    ready, fake_gemini
):
    state = _create(ready)
    sid = state["session"]["id"]
    fake_gemini.parse_fail.add("student")
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance=PLEDGE, understanding=35)
    turn = ready.post(_api(sid, "/say"), json={"content": ENCOURAGE}).json()
    assert _flags(turn) == {None}
    assert turn["agreement"]["count"] == 0
    assert turn["agreement"]["pledged_persona_ids"] == []


def test_pledge_latch_survives_later_stuck(ready, fake_gemini):
    state, _ = _pledge_turn(ready, fake_gemini)
    sid = state["session"]["id"]
    fake_gemini.results["student"] = _react(utterance=STUCK, understanding=40)
    turn = ready.post(_api(sid, "/say"), json={"content": "어때?"}).json()
    assert turn["agreement"]["count"] == 4
    assert sorted(turn["agreement"]["pledged_persona_ids"]) == _ids(
        state["personas"]
    )


def test_pledge_then_reaching_80_leaves_pledged_list(ready, fake_gemini):
    state, turn = _enter_then_say(
        ready,
        fake_gemini,
        _react(utterance=SAID, understanding=70),
        _react(utterance=PLEDGE, understanding=75),
        content=ENCOURAGE,
    )
    assert _stored(turn) == {70}
    assert _flags(turn) == {True}
    sid = state["session"]["id"]
    fake_gemini.results["student"] = _react(
        utterance="자료에서 2050년 인구가 줄어드는 걸 찾았어요.",
        understanding=90,
    )
    turn = ready.post(_api(sid, "/say"), json={"content": "찾았니?"}).json()
    assert turn["agreement"]["count"] == 4
    assert turn["agreement"]["pledged_persona_ids"] == []


def test_one_holdout_blocks_agree_advance(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    holdout = str(state["personas"][0]["source_record_id"])
    fake_gemini.results["student"] = _react(utterance=SAID, understanding=40)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.results["student"] = lambda key: _react(
        utterance=STUCK if key == holdout else PLEDGE, understanding=45
    )
    turn = ready.post(_api(sid, "/say"), json={"content": ENCOURAGE}).json()
    assert turn["agreement"]["count"] == 3
    assert sorted(turn["agreement"]["pledged_persona_ids"]) == _ids(
        state["personas"][1:]
    )
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 409
    assert _code(r) == "NOT_ALL_AGREED"


def test_regenerated_pledge_is_held_and_agrees(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    persona = state["personas"][0]
    fake_gemini.results["student"] = _react(utterance=SAID, understanding=20)
    ready.post(_api(sid, "/phases/0/enter"))
    fake_gemini.parse_fail.add(str(persona["source_record_id"]))
    ready.post(_api(sid, "/say"), json={"content": ENCOURAGE})

    fake_gemini.parse_fail.clear()
    fake_gemini.results["student"] = _react(utterance=PLEDGE, understanding=35)
    r = ready.post(_api(sid, "/regenerate"), json={"persona_id": persona["id"]})
    assert r.status_code == 200
    body = r.json()
    [fixed] = body["utterances"]
    assert fixed["structured"]["understanding"] == 20
    assert fixed["structured"]["pledge"] is True
    assert persona["id"] in body["agreement"]["agreed_persona_ids"]
    assert persona["id"] in body["agreement"]["pledged_persona_ids"]


def test_next_student_call_does_not_see_pledge_flag(
    ready, fake_gemini, monkeypatch
):
    state, turn = _pledge_turn(ready, fake_gemini)
    assert _flags(turn) == {True}
    prompts = []

    def recording(kind, **kw):
        if kind == "student":
            prompts.extend([kw["user"], kw["system"]])
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    ready.post(_api(state["session"]["id"], "/say"), json={"content": "어때?"})
    assert len(prompts) == 8
    assert not any("pledge" in p for p in prompts)
