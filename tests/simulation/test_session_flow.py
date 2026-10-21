"""말하기, 동의/Skip 전이, 종료, 복원 (#153)."""

import pytest

from app.services.simulation import gemini
from app.services.simulation.llm_schemas import StudentReaction


def _reaction(ready):
    return StudentReaction(
        action="고개를 끄덕인다",
        utterance="네!" if ready else "잘 모르겠어요.",
        artifact="",
        misconception="",
        ready_for_next=ready,
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
            {"name": f"국면{i}", "teacher_prompt": f"발문 {i}"}
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
            assert body["next_phase"]["name"] == f"국면{idx + 1}"
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
    turn = ready.post(_api(sid, "/phases/0/enter")).json()
    assert turn["agreement"]["count"] == 3
    assert turn["agreement"]["all_agreed"] is False

    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 409
    assert _code(r) == "NOT_ALL_AGREED"

    r = ready.post(_api(sid, "/advance"), json={"mode": "skip"})
    assert r.status_code == 200
    assert r.json()["current_phase_idx"] == 1
    state = ready.get(_api(sid)).json()
    assert state["utterances"][-1]["structured"] == {"type": "skip"}
    assert state["utterances"][-1]["phase_idx"] == 0
    # 새 국면은 아직 발화가 없고, 동의는 0
    assert state["agreement"] == {
        "phase_idx": 1,
        "agreed_persona_ids": [],
        "count": 0,
        "total": 4,
        "all_agreed": False,
    }


def test_failed_latest_reaction_blocks_agree(ready, fake_gemini):
    state = _create(ready)
    sid = state["session"]["id"]
    turn = ready.post(_api(sid, "/phases/0/enter")).json()
    assert turn["agreement"]["all_agreed"] is True

    failing = str(state["personas"][0]["source_record_id"])
    fake_gemini.parse_fail.add(failing)
    turn = ready.post(_api(sid, "/say"), json={"content": "하나 더"}).json()
    assert turn["failed_persona_ids"] == [state["personas"][0]["id"]]
    assert turn["agreement"]["count"] == 3

    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 409
    assert _code(r) == "NOT_ALL_AGREED"


def test_support_level_guard_lifts_after_user_turn(ready):
    state = _create(ready, level="Poor")
    sid = state["session"]["id"]
    assert {p["adapted_level"] for p in state["personas"]} == {"추가 지원 필요"}
    turn = ready.post(_api(sid, "/phases/0/enter")).json()
    assert turn["agreement"]["count"] == 0
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert _code(r) == "NOT_ALL_AGREED"
    turn = ready.post(_api(sid, "/say"), json={"content": "천천히 해 보자"})
    assert turn.json()["agreement"]["all_agreed"] is True
    r = ready.post(_api(sid, "/advance"), json={"mode": "agree"})
    assert r.status_code == 200


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


def test_next_student_call_sees_earlier_artifact_and_misconception(
    ready, fake_gemini, monkeypatch
):
    fake_gemini.results["student"] = StudentReaction(
        action="공책에 쓴다",
        utterance="다 했어요",
        artifact="3/4",
        misconception="분모끼리 더함",
        ready_for_next=True,
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
    assert all("3/4" in u and "분모끼리 더함" in u for u in student)
    stored = ready.get(_api(sid)).json()["utterances"]
    assert {u["content"] for u in stored if u["speaker_type"] == "student"} == {
        "다 했어요"
    }


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


def test_restore_returns_everything_in_seq_order(ready):
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
