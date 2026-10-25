"""관리자 시뮬레이션 로그 페이지와 API (#160, #280)."""

import pytest
from sqlalchemy import update

from app.models.simulation_session import SimulationSession

from .conftest import run
from .test_session_report import ENVELOPE


@pytest.fixture
def session_id(client, teacher, make_upload, fake_gemini):
    """교사 세션 1개: 국면 0 입장(시스템+교사+학생 2) + 말하기 1회."""
    make_upload(teacher)
    r = client.post(
        "/api/simulation/sessions",
        json={
            "random": {"n": 2, "grade": "all", "level": "all", "seed": 3},
            "phases": [{"name": "도입", "teacher_prompt": "발문"}],
        },
    )
    assert r.status_code == 201
    sid = r.json()["session"]["id"]
    r = client.post(f"/api/simulation/sessions/{sid}/phases/0/enter")
    assert r.status_code == 200
    r = client.post(
        f"/api/simulation/sessions/{sid}/say", json={"content": "질문"}
    )
    assert r.status_code == 200
    return sid


def test_non_admin_gets_403_on_page_and_api(client, session_id):
    for path in (
        "/admin/simulation/logs",
        "/admin/api/simulation/sessions",
        f"/admin/api/simulation/sessions/{session_id}",
        f"/admin/api/simulation/sessions/{session_id}/download",
    ):
        assert client.get(path).status_code == 403, path


def test_list_shows_sessions_with_utterance_count(
    client, as_user, admin, session_id
):
    as_user(admin)
    r = client.get("/admin/api/simulation/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["page"] == 1
    (row,) = body["sessions"]
    assert row["id"] == session_id
    assert row["username"] == "teacher1"
    assert row["persona_count"] == 2
    assert row["status"] == "running"
    # 입장: system + teacher(plan) + 2 students, 말하기: teacher + 2 students
    assert row["utterance_count"] == 7
    assert row["created_at"].endswith("+00:00")


def test_detail_includes_raw_profile_and_utterances(
    client, as_user, admin, session_id
):
    as_user(admin)
    r = client.get(f"/admin/api/simulation/sessions/{session_id}")
    assert r.status_code == 200
    state = r.json()
    assert state["session"]["id"] == session_id
    assert len(state["personas"]) == 2
    assert all(p["raw_profile"]["id"] for p in state["personas"])
    seqs = [u["seq"] for u in state["utterances"]]
    assert seqs == list(range(1, 8))
    assert state["session"]["created_at"].endswith("+00:00")
    assert state["utterances"][0]["created_at"].endswith("+00:00")


def test_detail_missing_session_404(client, as_user, admin):
    as_user(admin)
    r = client.get("/admin/api/simulation/sessions/999")
    assert r.status_code == 404


def test_page_renders_for_admin(client, as_user, admin):
    as_user(admin)
    r = client.get("/admin/simulation/logs")
    assert r.status_code == 200
    assert "/admin/api/simulation/sessions" in r.text


def test_status_shown_with_korean_labels(client, as_user, admin):
    as_user(admin)
    r = client.get("/admin/simulation/logs")
    assert "finished: '종료'" in r.text
    assert "STATUS_LABEL[s.status] ?? s.status" in r.text
    assert "STATUS_LABEL[state.session.status]" in r.text


def _set_feedback(sim_db, sid, envelope):
    async def _go():
        async with sim_db() as db:
            await db.execute(
                update(SimulationSession)
                .where(SimulationSession.id == sid)
                .values(status="finished", feedback_json=envelope)
            )
            await db.commit()

    run(_go())


def test_detail_feedback_null_then_envelope(
    client, sim_db, as_user, admin, session_id
):
    as_user(admin)
    url = f"/admin/api/simulation/sessions/{session_id}"
    assert client.get(url).json()["feedback"] is None
    _set_feedback(sim_db, session_id, ENVELOPE)
    assert client.get(url).json()["feedback"] == ENVELOPE


def test_download_markdown_with_feedback(
    client, sim_db, as_user, admin, session_id
):
    _set_feedback(sim_db, session_id, ENVELOPE)
    as_user(admin)
    r = client.get(f"/admin/api/simulation/sessions/{session_id}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/markdown; charset=utf-8"
    assert r.headers["content-disposition"] == (
        f'attachment; filename="simulation_{session_id}.md"'
    )
    assert "teacher1" in r.text
    assert "- **교사**: 질문" in r.text.splitlines()
    assert "참여 편중" in r.text.split("## 피드백", 1)[1]


def test_download_without_feedback_is_transcript_only(
    client, as_user, admin, session_id
):
    as_user(admin)
    r = client.get(f"/admin/api/simulation/sessions/{session_id}/download")
    assert r.status_code == 200
    assert "## 대화록" in r.text
    assert "피드백이 아직 생성되지 않았습니다." in r.text


def test_download_missing_session_404(client, as_user, admin):
    as_user(admin)
    r = client.get("/admin/api/simulation/sessions/999/download")
    assert r.status_code == 404


def test_page_has_feedback_section_and_download_link(client, as_user, admin):
    as_user(admin)
    r = client.get("/admin/simulation/logs")
    assert 'id="detailFeedback"' in r.text
    assert "Markdown 다운로드" in r.text
    assert "/download" in r.text
    assert "피드백 없음" in r.text
