"""지난 세션 목록과 다른 학생으로 다시 실행 (#157)."""

from types import SimpleNamespace

import pytest

from app.templating import templates

LIST = "/api/simulation/sessions"
PHASES = [{"name": "도입", "teacher_prompt": "오늘은 지도를 봅니다"}]


def _create(client, seed=1, phases=PHASES):
    r = client.post(
        "/api/simulation/sessions",
        json={"random": {"n": 2, "seed": seed}, "phases": phases},
    )
    assert r.status_code == 201
    return r.json()["session"]


@pytest.fixture
def ready(client, teacher, make_upload, fake_gemini):
    make_upload(teacher)
    return client


def test_lists_own_sessions_newest_first(
    ready, as_user, teacher, other_teacher, make_upload
):
    first = _create(ready, seed=1)
    second = _create(ready, seed=2)
    as_user(other_teacher)
    make_upload(other_teacher)
    foreign = _create(ready, seed=3)
    assert [s["id"] for s in ready.get(LIST).json()["sessions"]] == [
        foreign["id"]
    ]

    as_user(teacher)
    r = ready.get(LIST)
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert [s["id"] for s in sessions] == [second["id"], first["id"]]
    assert sessions[0] == {
        "id": second["id"],
        "created_at": second["created_at"],
        "persona_count": 2,
        "status": "running",
        "has_feedback": False,
        "upload_id": second["upload_id"],
        "current_phase_idx": 0,
        "phase_count": 1,
    }


def test_upload_id_filter_and_latest_upload_flag(ready, teacher, make_upload):
    old = _create(ready, seed=1)
    assert old["is_latest_upload"] is True
    new_upload = make_upload(teacher, text="Second lesson about rivers")
    new = _create(ready, seed=2)
    assert new["upload_id"] == new_upload

    r = ready.get(LIST, params={"upload_id": old["upload_id"]})
    assert [s["id"] for s in r.json()["sessions"]] == [old["id"]]
    r = ready.get(LIST, params={"upload_id": new_upload})
    assert [s["id"] for s in r.json()["sessions"]] == [new["id"]]

    def latest(sid):
        state = ready.get(f"/api/simulation/sessions/{sid}").json()
        return state["session"]["is_latest_upload"]

    assert latest(old["id"]) is False
    assert latest(new["id"]) is True


def test_rerun_setup_draft_inherits_previous_phases(ready, fake_gemini):
    phases = [
        {"name": "도입", "teacher_prompt": "지도를 펼쳐 볼까요?"},
        {"name": "모둠 활동", "teacher_prompt": "우리 동네를 찾아봅시다"},
    ]
    sid = _create(ready, phases=phases)["id"]
    ready.post(f"/api/simulation/sessions/{sid}/finish")
    splits = fake_gemini.count("phase_split")

    assert ready.get("/simulation/setup").status_code == 200
    body = ready.get("/api/simulation/phases/draft").json()
    assert body["source"] == "inherited"
    assert [(p["name"], p["teacher_prompt"]) for p in body["phases"]] == [
        (p["name"], p["teacher_prompt"]) for p in phases
    ]
    assert fake_gemini.count("phase_split") == splits


def test_feedback_page_has_rerun_link_to_setup(ready):
    sid = _create(ready)["id"]
    html = ready.get(f"/simulation/sessions/{sid}/feedback").text
    assert 'href="/simulation/setup" id="rerunBtn"' in html
    assert "다른 학생으로 다시 실행" in html


def test_dashboard_includes_session_list():
    request = SimpleNamespace(
        session={"user_id": 1}, url=SimpleNamespace(path="/dashboard")
    )
    html = templates.get_template("user/dashboard.html").render(
        request=request,
        user=SimpleNamespace(username="t", nickname="t", is_admin=False),
        document=None,
        criteria_documents=[],
    )
    assert 'id="simSessions"' in html
    assert 'fetch("/api/simulation/sessions"' in html
