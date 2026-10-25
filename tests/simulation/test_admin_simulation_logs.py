"""관리자 시뮬레이션 로그 페이지와 API (#160, #280)."""

import io
import zipfile
from urllib.parse import unquote

import pytest
from sqlalchemy import update

from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_session import SimulationSession
from app.schemas.admin_export import ExportFilters
from app.services.admin_export_service import AdminExportService

from .conftest import run
from .test_session_report import ENVELOPE

KOREAN_PLAN = "우리나라 미래 인구 구성비 및 우리 교실 내의 변화를 예측하기.pdf"


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
    assert r.headers["content-disposition"].startswith(
        f'attachment; filename="simulation_{session_id}.md"; '
        "filename*=UTF-8''"
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


def _rename_upload(sim_db, sid, original, filename=None):
    async def _go():
        async with sim_db() as db:
            session = await db.get(SimulationSession, sid)
            values = {"original_filename": original}
            if filename:
                values["filename"] = filename
            await db.execute(
                update(LessonPlanUpload)
                .where(LessonPlanUpload.id == session.upload_id)
                .values(**values)
            )
            await db.commit()
            return session.user_id, session.upload_id

    return run(_go())


def _disposition_name(header):
    return unquote(header.split("filename*=UTF-8''", 1)[1])


def test_download_korean_lessonplan_name_in_header_and_body(
    client, sim_db, as_user, admin, session_id
):
    user_id, upload_id = _rename_upload(sim_db, session_id, KOREAN_PLAN)
    as_user(admin)
    r = client.get(f"/admin/api/simulation/sessions/{session_id}/download")
    assert r.status_code == 200
    assert _disposition_name(r.headers["content-disposition"]) == (
        f"u{user_id:05d}__simsession_{upload_id}__"
        f"{KOREAN_PLAN.removesuffix('.pdf')}__s{session_id}.md"
    )
    assert f"- 지도안: {KOREAN_PLAN}" in r.text.splitlines()


def test_download_falls_back_to_stored_filename(
    client, sim_db, as_user, admin, session_id
):
    user_id, upload_id = _rename_upload(
        sim_db, session_id, None, filename="saved_1.pdf"
    )
    as_user(admin)
    r = client.get(f"/admin/api/simulation/sessions/{session_id}/download")
    assert "- 지도안: saved_1.pdf" in r.text.splitlines()
    assert _disposition_name(r.headers["content-disposition"]) == (
        f"u{user_id:05d}__simsession_{upload_id}__saved_1__s{session_id}.md"
    )


def test_download_matches_export_zip_bytes(
    client, sim_db, as_user, admin, session_id
):
    _rename_upload(sim_db, session_id, KOREAN_PLAN)
    as_user(admin)
    r = client.get(f"/admin/api/simulation/sessions/{session_id}/download")
    name = _disposition_name(r.headers["content-disposition"])

    async def _go():
        async with sim_db() as db:
            svc = AdminExportService(db)
            return b"".join(svc.stream_zip(await svc.collect(ExportFilters())))

    zf = zipfile.ZipFile(io.BytesIO(run(_go())))
    assert zf.read(f"simulations/{name}") == r.content


def test_page_shows_lessonplan_name_via_text_content(client, as_user, admin):
    as_user(admin)
    r = client.get("/admin/simulation/logs")
    assert 'id="detailLessonplan"' in r.text
    assert "`지도안: ${state.session.lessonplan_filename}`" in r.text
