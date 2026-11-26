"""대화록·시뮬레이션 피드백 생성·캐시·다운로드 (#156)."""

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.simulation_session import SimulationSession
from app.models.simulation_utterance import SimulationUtterance
from app.services.simulation import feedback, gemini
from app.services.simulation.llm_schemas import (
    FeedbackResult,
    FeedbackResultWithSupports,
    IndividualSupport,
    StudentReaction,
    UtteranceSuggestion,
)
from tests.simulation.conftest import run


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


def _saved_report(sim_db, sid):
    """generate()가 feedback_report_path에 저장한 Markdown (#279)."""

    async def _go():
        async with sim_db() as db:
            return (await db.get(SimulationSession, sid)).feedback_report_path

    return Path(run(_go())).read_text(encoding="utf-8")


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
        "individual_supports",
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
        understanding=70,
        confidence=0.5,
        on_task=True,
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


def test_feedback_input_drops_stuck_summary_misconception(
    ready, fake_gemini, monkeypatch
):
    """'…모름'은 오개념이 아니므로 [오개념:] 태그로 넘기지 않는다 (#302)."""
    fake_gemini.results["student"] = StudentReaction(
        action="고민한다",
        utterance="어떻게 시작하죠?",
        artifact="",
        misconception="비교를 어떻게 시작해야 할지 모름",
        ready_for_next=False,
        understanding=50,
        confidence=0.5,
        on_task=True,
    )
    sid = _finished(ready)
    prompts = []

    def recording(kind, **kw):
        prompts.append((kind, kw["user"]))
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    assert ready.post(_api(sid, "/feedback")).status_code == 200
    [(_, user)] = prompts
    assert "어떻게 시작하죠?" in user
    assert "[오개념:" not in user and "시작해야 할지 모름" not in user


def test_feedback_input_drops_stuck_only_misconception(
    ready, fake_gemini, monkeypatch
):
    """질문·'모르겠어요'만 한 반응의 오개념은 [오개념:] 태그로 넘기지 않는다 (#330)."""
    fake_gemini.results["student"] = StudentReaction(
        action="고민한다",
        utterance="피자... 조각이요...? 잘 모르겠어요...",
        artifact="",
        misconception="노인 인구 비율이 늘면 전체 사람 수도 늘어난다고 생각함",
        ready_for_next=False,
        understanding=30,
        confidence=0.5,
        on_task=True,
    )
    sid = _finished(ready)
    prompts = []

    def recording(kind, **kw):
        prompts.append((kind, kw["user"]))
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    assert ready.post(_api(sid, "/feedback")).status_code == 200
    [(_, user)] = prompts
    assert "피자... 조각이요...?" in user
    assert "[오개념:" not in user and "전체 사람 수도" not in user


def test_feedback_input_drops_hard_words_question_misconception(
    ready, fake_gemini, monkeypatch
):
    """질문과 함께 '어려운 내용 같은데요'만 한 반응은 [오개념:]이 없다 (#341)."""
    fake_gemini.results["student"] = StudentReaction(
        action="고개를 갸웃한다",
        utterance=(
            "선생님, 다중공선성이나 명분할 오류 같은 단어들은 중학교나 고등학교 "
            "수학에서도 어려운 내용 같은데요. 저희가 오늘 실제로 엑셀이나 엔트리로 "
            "그래프를 그릴 때 이 복잡한 계산을 전부 다 직접 해야 하는 건가요?"
        ),
        artifact="",
        misconception="복잡한 계산을 전부 직접 해야 한다고 오해함",
        ready_for_next=False,
        understanding=30,
        confidence=0.5,
        on_task=True,
    )
    sid = _finished(ready)
    prompts = []

    def recording(kind, **kw):
        prompts.append((kind, kw["user"]))
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    assert ready.post(_api(sid, "/feedback")).status_code == 200
    [(_, user)] = prompts
    assert "다중공선성" in user
    assert "[오개념:" not in user and "직접 해야 한다고 오해함" not in user


def test_turn_note_stays_out_of_stored_rows_feedback_and_report(
    ready, fake_gemini, monkeypatch, sim_db
):
    """후속 턴 안내문은 학생 호출에만 붙고 저장·피드백·보고서로 새지 않는다 (#353)."""
    prompts = []

    def recording(kind, **kw):
        prompts.append((kind, kw["user"]))
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    sid = _finished(ready)
    assert any(k == "student" and "[이번 반응]" in u for k, u in prompts)

    prompts.clear()
    assert ready.post(_api(sid, "/feedback")).status_code == 200
    [(kind, user)] = prompts
    assert kind == "feedback" and "[이번 반응]" not in user
    assert "[이번 반응]" not in _saved_report(sim_db, sid)

    async def _rows():
        async with sim_db() as db:
            q = select(SimulationUtterance).where(
                SimulationUtterance.session_id == sid
            )
            return (await db.scalars(q)).all()

    rows = run(_rows())
    assert rows
    for u in rows:
        assert "[이번 반응]" not in u.content
        assert "[이번 반응]" not in json.dumps(u.structured, ensure_ascii=False)


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


def test_download_route_is_gone_but_report_is_saved(ready, sim_db, tmp_path):
    sid = _finished(ready)
    ready.post(_api(sid, "/feedback"))

    # 사용자 Markdown 다운로드는 인쇄로 대체했다 (#279)
    assert ready.get(_api(sid, "/feedback/download")).status_code == 404
    md = _saved_report(sim_db, sid)
    assert md.startswith("# 수업 시뮬레이션 피드백(가설)")
    assert feedback.DISCLAIMER in md
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
    assert "인쇄 / PDF 저장" in r.text
    r = ready.get(f"/simulation/sessions/{sid}/feedback")
    assert r.status_code == 200
    assert "인쇄 / PDF 저장" in r.text
    assert "보고서 Markdown 저장" not in r.text
    assert feedback.DISCLAIMER in r.text
    # 위험 시나리오 아래 1번, ①–④ 탭 본문 위 1번
    assert r.text.count(feedback.SECTION_NOTE) == 2
    assert "④ 개별 지원" in r.text
    # 키가 없는 옛 feedback_json에서도 스크립트가 멈추지 않는다 (#395)
    assert "fb.individual_supports || []" in r.text


SURVEY_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfXwRv2PdV4izYZGdJADiRUWdopZPbW0gXlESBATjqx9ZnBmg/viewform?usp=publish-editor"


def test_feedback_page_has_survey_modal(ready):
    # 피드백 화면을 떠날 때 설문 모달 (#289)
    sid = _finished(ready)
    r = ready.get(f"/simulation/sessions/{sid}/feedback")
    assert r.status_code == 200
    assert 'id="surveyModal"' in r.text
    assert SURVEY_URL in r.text
    assert "설문참여 완료" in r.text
    assert 'id="backBtn"' in r.text
    r = ready.get(f"/simulation/sessions/{sid}/transcript")
    assert r.status_code == 200
    assert "surveyModal" not in r.text


def test_report_pages_include_plan_and_people_section(ready):
    # 지도안 파일명·참여 학생 공용 include (#283)
    sid = _finished(ready)
    for page in ("transcript", "feedback"):
        r = ready.get(f"/simulation/sessions/{sid}/{page}")
        assert r.status_code == 200
        assert 'id="simPlan"' in r.text
        assert 'id="simPeople"' in r.text
        assert "renderReportMeta(state)" in r.text


@pytest.mark.parametrize(
    "original, expected",
    [("우리 교실 지도안.pdf", "우리 교실 지도안.pdf"), (None, "plan_0.pdf")],
)
def test_state_has_lessonplan_filename(ready, tmp_path, original, expected):
    sid = _create(ready)
    conn = sqlite3.connect(tmp_path / "sim.db")
    with conn:
        conn.execute(
            "UPDATE lessonplan_uploads SET original_filename=?", (original,)
        )
    conn.close()
    state = ready.get(_api(sid)).json()
    assert state["session"]["lessonplan_filename"] == expected
    assert state["personas"]
    assert all("raw_profile" not in p for p in state["personas"])


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


def _teacher_seq(client, sid):
    state = client.get(_api(sid)).json()
    [seq] = [
        u["seq"]
        for u in state["utterances"]
        if u["speaker_type"] == "teacher" and u["content"] == "질문"
    ]
    return seq


def _suggest(fake_gemini, teacher_seq, phase_idx=0):
    base = fake_gemini.results["feedback"]
    fake_gemini.results["feedback"] = base.model_copy(
        update={
            "utterance_suggestions": [
                UtteranceSuggestion(
                    phase_idx=phase_idx,
                    actual="요약문",
                    suggested="무엇을 알아볼까요?",
                    intent="흥미 유발",
                    teacher_seq=teacher_seq,
                )
            ]
        }
    )


def test_actual_is_quoted_verbatim_from_transcript(ready, fake_gemini, sim_db):
    """모델이 요약해도 teacher_seq로 대화록 원문을 인용한다 (#178)."""
    sid = _finished(ready)
    _suggest(fake_gemini, _teacher_seq(ready, sid))

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    assert r.json()["feedback"]["utterance_suggestions"][0]["actual"] == "질문"
    md = _saved_report(sim_db, sid)
    assert "- 실제 발화: 질문" in md
    assert "요약문" not in md


@pytest.mark.parametrize("teacher_seq", [None, 9999])
def test_actual_keeps_model_text_without_matching_seq(
    ready, fake_gemini, teacher_seq
):
    sid = _finished(ready)
    _suggest(fake_gemini, teacher_seq)

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    got = r.json()["feedback"]["utterance_suggestions"][0]
    assert got["actual"] == "요약문"
    assert got["phase_idx"] == 0


def test_phase_idx_follows_matched_teacher_line(ready, fake_gemini, sim_db):
    """모델이 1-기준 번호를 줘도 교사 발화의 장면으로 맞춘다 (#365)."""
    sid = _finished(ready)
    _suggest(fake_gemini, _teacher_seq(ready, sid), phase_idx=5)

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    assert r.json()["feedback"]["utterance_suggestions"][0]["phase_idx"] == 0
    md = _saved_report(sim_db, sid)
    assert "### 도입" in md
    assert "### 장면 6" not in md


def test_phase_idx_out_of_range_is_clamped_without_seq(ready, fake_gemini):
    sid = _finished(ready)
    _suggest(fake_gemini, None, phase_idx=99)

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    assert r.json()["feedback"]["utterance_suggestions"][0]["phase_idx"] == 1


def _finished_with_one_on_one(client):
    """_finished와 같되 장면 0에서 첫 학생에게 1:1 발화를 한 번 더 한다."""
    sid = _create(client)
    assert (
        client.post(_api(sid, "/say"), json={"content": "질문"}).status_code
        == 200
    )
    target = client.get(_api(sid)).json()["personas"][0]
    r = client.post(
        _api(sid, "/say"),
        json={"content": "너는?", "target_persona_id": target["id"]},
    )
    assert r.status_code == 200
    r = client.post(_api(sid, "/advance"), json={"mode": "skip"})
    assert r.status_code == 200
    assert client.post(_api(sid, "/phases/1/enter")).status_code == 200
    assert client.post(_api(sid, "/finish")).status_code == 200
    return sid, target


def _support_seq(client, sid, content):
    state = client.get(_api(sid)).json()
    [seq] = [
        u["seq"]
        for u in state["utterances"]
        if u["speaker_type"] == "teacher" and u["content"] == content
    ]
    return seq


def _support(fake_gemini, teacher_seq, phase_idx=5, persona="다른이름"):
    base = fake_gemini.results["feedback"]
    fake_gemini.results["feedback"] = base.model_copy(
        update={
            "individual_supports": [
                IndividualSupport(
                    persona=persona,
                    phase_idx=phase_idx,
                    teacher_seq=teacher_seq,
                    what_worked="말이 길어졌다",
                    plan_suggestion="활동1에 개별 확인 발문을 둔다",
                )
            ]
        }
    )


def test_individual_support_is_filled_from_one_on_one_line(
    ready, fake_gemini, sim_db
):
    """학생·장면·인용은 teacher_seq가 가리키는 1:1 발화에서 채운다 (#395)."""
    sid, target = _finished_with_one_on_one(ready)
    _support(fake_gemini, _support_seq(ready, sid, "너는?"))

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    [got] = r.json()["feedback"]["individual_supports"]
    assert got["phase_idx"] == 0
    assert got["persona"] == target["display_name"]
    assert got["actual"] == "너는?"
    md = _saved_report(sim_db, sid)
    assert f"### 도입 · {target['display_name']}" in md
    assert "- 1:1 발화: 너는?" in md
    assert "다른이름" not in md


@pytest.mark.parametrize("seq", [None, 9999, "whole_class"])
def test_individual_support_without_one_on_one_line_is_dropped(
    ready, fake_gemini, seq
):
    sid, _ = _finished_with_one_on_one(ready)
    if seq == "whole_class":
        seq = _support_seq(ready, sid, "질문")
    _support(fake_gemini, seq)

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    assert r.json()["feedback"]["individual_supports"] == []


def test_session_without_one_on_one_has_no_supports(ready, fake_gemini, sim_db):
    sid = _finished(ready)
    _support(fake_gemini, _teacher_seq(ready, sid))

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    assert r.json()["feedback"]["individual_supports"] == []
    assert feedback.NO_SUPPORTS in _saved_report(sim_db, sid)


def test_one_on_one_session_requires_supports_in_schema(ready, fake_gemini):
    """1:1 교사 발화가 있으면 ④를 비우지 못하는 스키마로 부른다 (#406)."""
    sid, _ = _finished_with_one_on_one(ready)

    assert ready.post(_api(sid, "/feedback")).status_code == 200
    assert fake_gemini.schemas[-1] is FeedbackResultWithSupports


def test_whole_class_only_session_keeps_plain_schema(ready, fake_gemini):
    """학생 이름을 부른 전체 발화는 1:1로 세지 않는다 (#406)."""
    sid = _create(ready)
    name = ready.get(_api(sid)).json()["personas"][0]["display_name"]
    r = ready.post(_api(sid, "/say"), json={"content": f"{name}, 네 차례예요"})
    assert r.status_code == 200
    assert (
        ready.post(_api(sid, "/advance"), json={"mode": "skip"}).status_code
        == 200
    )
    assert ready.post(_api(sid, "/phases/1/enter")).status_code == 200
    assert ready.post(_api(sid, "/finish")).status_code == 200

    assert ready.post(_api(sid, "/feedback")).status_code == 200
    assert fake_gemini.schemas[-1] is FeedbackResult


def test_empty_supports_from_model_falls_back_to_plain_parse(
    ready, fake_gemini, monkeypatch, sim_db
):
    """모델이 minItems를 어겨 빈 ④를 내면 502가 아니라 빈 ④로 받는다 (#406)."""
    sid, _ = _finished_with_one_on_one(ready)

    def strict(kind, **kw):
        result = fake_gemini(kind, **kw)
        if kind == "feedback":
            result = dataclasses.replace(result, parsed=None)
        return result

    monkeypatch.setattr(gemini, "call_structured", strict)

    r = ready.post(_api(sid, "/feedback"))
    assert r.status_code == 200
    assert r.json()["feedback"]["individual_supports"] == []
    assert feedback.NO_SUPPORTS in _saved_report(sim_db, sid)


def test_feedback_input_numbers_teacher_lines(ready, fake_gemini, monkeypatch):
    sid = _finished(ready)
    seq = _teacher_seq(ready, sid)
    prompts = []

    def recording(kind, **kw):
        prompts.append(kw["user"])
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    assert ready.post(_api(sid, "/feedback")).status_code == 200
    assert f"교사(전체) #{seq}: 질문" in prompts[0]


def test_feedback_input_extracts_plan_off_event_loop_thread(
    ready, fake_gemini, monkeypatch, extract_on_loop
):
    # (#453) 입력 문자열은 그대로, 추출만 루프 밖 스레드에서
    sid = _finished(ready)
    prompts = []

    def recording(kind, **kw):
        prompts.append(kw["user"])
        return fake_gemini(kind, **kw)

    monkeypatch.setattr(gemini, "call_structured", recording)
    assert ready.post(_api(sid, "/feedback")).status_code == 200
    [user] = prompts
    assert user.startswith("[지도안 전문]\nIntro lesson about maps\n\n[장면]\n")
    assert extract_on_loop == [False]
