"""관리자용 세션 문서(대화록 + 피드백) Markdown 생성기 (#280)."""

from datetime import datetime
from types import SimpleNamespace

from app.services.simulation import feedback
from app.services.simulation.session_report import render_session_markdown

ENVELOPE = {
    "feedback": {
        "risk_scenarios": [
            {
                "title": "참여 편중",
                "scene": "한 학생이 질문을 독점한다.",
                "evidence_type": "상호작용",
            }
        ],
        "utterance_suggestions": [
            {
                "phase_idx": 0,
                "actual": "질문해 보세요.",
                "suggested": "한 사람씩 말해 볼까요?",
                "intent": "발언 기회 분산",
            }
        ],
        "progress_directions": ["예시를 먼저 보여 준다."],
        "change_directions": [{"kind": "자료", "content": "반례를 더한다."}],
    },
    "model_name": "fake-model",
    "latency_ms": 1000,
    "guideline_version": None,
    "created_at": "2026-10-21T10:00:00",
}


def _u(seq, speaker, content, phase=0, persona=None, target=None, ok=True):
    return SimpleNamespace(
        seq=seq,
        phase_idx=phase,
        speaker_type=speaker,
        persona_id=persona,
        target_persona_id=target,
        content=content,
        structured={"ready_for_next": True} if ok else None,
    )


def _render(feedback_json=None, utterances=None, emoji=""):
    session = SimpleNamespace(
        id=7,
        status="finished",
        created_at=datetime(2026, 10, 21, 9, 0),
        finished_at=datetime(2026, 10, 21, 9, 30),
        persona_count=2,
        model_name="sim-model",
        feedback_json=feedback_json,
    )
    phases = [
        SimpleNamespace(idx=0, name="도입" + emoji),
        SimpleNamespace(idx=1, name="전개"),
    ]
    personas = [
        SimpleNamespace(
            id=11,
            display_name="민준" + emoji,
            adapted_level="중",
            source="dataset",
        ),
        SimpleNamespace(
            id=12, display_name="서연", adapted_level="상", source="custom"
        ),
    ]
    if utterances is None:
        utterances = [
            _u(1, "system", "도입 국면 시작", ok=False),
            _u(2, "teacher", "질문해 보세요."),
            _u(3, "student", "저요!", persona=11),
            _u(4, "teacher", "너는?", phase=1, target=12),
            _u(5, "student", "모르겠어요", phase=1, persona=12),
        ]
    return render_session_markdown(
        session, "teacher1", phases, personas, utterances
    )


def test_header_personas_and_transcript_grouped_by_phase():
    md = _render()
    assert md.startswith("# ")
    for text in (
        "7",
        "teacher1",
        "2026-10-21T09:00:00+00:00",
        "2026-10-21T09:30:00+00:00",
        "sim-model",
        "## 페르소나",
        "- 민준 · 중 · dataset",
        "- 서연 · 상 · custom",
        "## 대화록",
    ):
        assert text in md, text
    lines = md.splitlines()
    intro, develop = lines.index("### 도입"), lines.index("### 전개")
    assert intro < lines.index("- **시스템**: 도입 국면 시작") < develop
    assert intro < lines.index("- **교사**: 질문해 보세요.") < develop
    assert lines.index("- **민준**: 저요!") < develop
    assert develop < lines.index("- **서연**: 모르겠어요")


def test_targeted_teacher_utterance_names_target():
    assert "- **교사 (서연에게)**: 너는?" in _render().splitlines()


def test_failed_student_utterance_is_marked():
    md = _render(utterances=[_u(1, "student", "원문", persona=11, ok=False)])
    assert "- **민준**: (파싱 실패) 원문" in md.splitlines()


def test_without_feedback_says_not_generated():
    md = _render()
    tail = md.split("## 피드백", 1)[1]
    assert tail.strip() == "피드백이 아직 생성되지 않았습니다."


def test_with_feedback_reuses_render_markdown_body_without_title():
    md = _render(feedback_json=ENVELOPE)
    tail = md.split("## 피드백", 1)[1]
    assert feedback.TITLE not in md
    assert feedback.DISCLAIMER in tail
    for text in (
        "참여 편중",
        "한 사람씩 말해 볼까요?",
        "예시를 먼저 보여 준다.",
        "반례를 더한다.",
    ):
        assert text in tail, text


def test_emojis_are_stripped_from_utterances_and_feedback():
    envelope = {
        **ENVELOPE,
        "feedback": {
            **ENVELOPE["feedback"],
            "progress_directions": ["\U0001f449 예시"],
        },
    }
    md = _render(
        feedback_json=envelope,
        utterances=[
            _u(1, "student", "좋아요 \U0001f525", persona=11),
            _u(2, "teacher", "너는?", target=11),
        ],
        emoji=" \U0001f600",
    )
    assert not any(e in md for e in ("\U0001f600", "\U0001f525", "\U0001f449"))
    lines = md.splitlines()
    assert "### 도입" in lines
    assert "- 민준 · 중 · dataset" in lines
    assert "- **민준**: 좋아요" in lines
    assert "- **교사 (민준에게)**: 너는?" in lines
