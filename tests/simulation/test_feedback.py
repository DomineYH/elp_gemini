"""대화록·시뮬레이션 피드백 생성·캐시·다운로드 (#156)."""

import json
import sqlite3

import pytest

from app.services.simulation import feedback, gemini
from app.services.simulation.llm_schemas import StudentReaction


def _api(sid, path=""):
    return f"/api/simulation/sessions/{sid}{path}"


def _code(r):
    return r.json()["detail"]["code"]


def _create(client):
    cands = client.get(
        "/api/simulation/candidates", params={"n": 2, "seed": 3}
    ).json()["candidates"]
    r = client.post(
        "/api/simulation/sessions",
        json={
            "personas": [
                {"ref": c["ref"], "pseudonym": c["pseudonym"]} for c in cands
            ],
            "phases": [
                {"name": "도입", "teacher_prompt": "발문 0"},
                {"name": "정리", "teacher_prompt": "발문 1"},
            ],
        },
    )
    assert r.status_code == 201
    sid = r.json()["session"]["id"]
    assert client.post(_api(sid, "/phases/0/enter")).status_code == 200
    return sid


def _finished(client):
    sid = _create(client)
    r = client.post(_api(sid, "/say"), json={"content": "질문"})
    assert r.status_code == 200
    r = client.post(_api(sid, "/advance"), json={"mode": "skip"})
    assert r.status_code == 200
    assert client.post(_api(sid, "/phases/1/enter")).status_code == 200
    assert client.post(_api(sid, "/finish")).status_code == 200
    return sid


@pytest.fixture
def ready(client, teacher, make_upload, fake_gemini, tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "REPORTS_DIR", str(tmp_path / "reports"))
    make_upload(teacher)
    return client


def test_finished_session_feedback_is_generated_once_then_cached(
    ready, fake_gemini
):
    sid = _finished(ready)

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is False
    assert body["model_name"] == "fake-model"
    assert body["latency_ms"] == 1
    assert body["guideline_version"] is None
    assert body["created_at"]
    assert body["feedback"]["risk_scenarios"][0]["title"] == "전이 지연"
    assert set(body["feedback"]) == {
        "risk_scenarios",
        "utterance_suggestions",
        "progress_directions",
        "change_directions",
    }
    assert fake_gemini.count("feedback") == 1

    again = ready.post(_api(sid, "/feedback"))
    assert again.status_code == 200
    assert again.json()["cached"] is True
    assert again.json()["feedback"] == body["feedback"]
    assert fake_gemini.count("feedback") == 1

    got = ready.get(_api(sid, "/feedback"))
    assert got.status_code == 200
    assert got.json()["feedback"] == body["feedback"]
    state = ready.get(_api(sid)).json()
    assert state["session"]["has_feedback"] is True


def test_feedback_input_has_student_artifact_and_misconception(
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
    sid = _finished(ready)
    prompts = []

    def recording(kind, **kw):
        prompts.append((kind, kw["user"]))
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    assert ready.post(_api(sid, "/feedback")).status_code == 200
    [(kind, user)] = prompts
    assert kind == "feedback"
    assert "3/4" in user and "분모끼리 더함" in user


def test_running_session_is_refused(ready, fake_gemini):
    sid = _create(ready)
    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 409
    assert _code(r) == "SESSION_NOT_FINISHED"
    assert fake_gemini.count("feedback") == 0


def test_parse_failure_is_502_and_nothing_is_cached(ready, fake_gemini):
    sid = _finished(ready)
    fake_gemini.parse_fail.add("feedback")

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 502
    assert _code(r) == "FEEDBACK_PARSE_FAILED"
    assert _code(ready.get(_api(sid, "/feedback"))) == "NO_FEEDBACK"
    assert ready.get(_api(sid)).json()["session"]["has_feedback"] is False

    fake_gemini.parse_fail.clear()
    assert ready.post(_api(sid, "/feedback")).json()["cached"] is False
    assert fake_gemini.count("feedback") == 2


def test_quota_is_429_with_retry_after(ready, fake_gemini):
    sid = _finished(ready)
    fake_gemini.quota.add("feedback")
    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "30"
    assert _code(ready.get(_api(sid, "/feedback"))) == "NO_FEEDBACK"


def test_download_returns_markdown_report(ready, tmp_path):
    sid = _finished(ready)
    assert _code(ready.get(_api(sid, "/feedback/download"))) == "NO_FEEDBACK"
    ready.post(_api(sid, "/feedback"))

    r = ready.get(_api(sid, "/feedback/download"))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("# 수업 시뮬레이션 피드백(가설)")
    assert feedback.DISCLAIMER in r.text
    # 분석 보고서와 같은 저장 서비스·디렉터리 규칙(ADR 0001)
    saved = list(
        (tmp_path / "reports").glob(f"*/*simulation_{sid}_*_reports.md")
    )
    assert len(saved) == 1


def test_other_user_gets_404_everywhere(ready, as_user, other_teacher):
    sid = _finished(ready)
    ready.post(_api(sid, "/feedback"))
    as_user(other_teacher)
    for r in (
        ready.post(_api(sid, "/feedback")),
        ready.get(_api(sid, "/feedback")),
        ready.get(_api(sid, "/feedback/download")),
    ):
        assert r.status_code == 404
        assert _code(r) == "SESSION_NOT_FOUND"
    for page in ("transcript", "feedback"):
        r = ready.get(f"/simulation/sessions/{sid}/{page}")
        assert r.status_code == 404


def test_transcript_and_feedback_pages_render(ready):
    sid = _finished(ready)
    r = ready.get(f"/simulation/sessions/{sid}/transcript")
    assert r.status_code == 200
    assert "AI 피드백 받기" in r.text
    r = ready.get(f"/simulation/sessions/{sid}/feedback")
    assert r.status_code == 200
    assert "보고서 Markdown 저장" in r.text
    assert feedback.DISCLAIMER in r.text
    # 위험 시나리오 아래 1번, ①②③ 탭 본문 위 1번
    assert r.text.count(feedback.SECTION_NOTE) == 2


def test_concurrent_generation_returns_first_envelope_and_one_file(
    ready, fake_gemini, tmp_path, monkeypatch
):
    sid = _finished(ready)
    reports = tmp_path / "reports"
    prior = {
        "feedback": {
            **fake_gemini.results["feedback"].model_dump(),
            "progress_directions": ["먼저 저장된 피드백"],
        },
        "model_name": "fake-model",
        "latency_ms": 1,
        "guideline_version": None,
        "created_at": "2026-10-21T00:00:00+00:00",
    }

    def other_request_wins(kind, **kw):
        # 같은 세션의 다른 POST가 Gemini 호출 중에 먼저 저장을 끝낸다
        other = reports / "1" / "other_reports.md"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("first")
        conn = sqlite3.connect(tmp_path / "sim.db")
        with conn:
            conn.execute(
                "UPDATE simulation_sessions SET feedback_json=? WHERE id=?",
                (json.dumps(prior, ensure_ascii=False), sid),
            )
        conn.close()
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", other_request_wins)
    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    assert r.json() == {**prior, "cached": True}
    assert [p.name for p in reports.rglob("*.md")] == ["other_reports.md"]
