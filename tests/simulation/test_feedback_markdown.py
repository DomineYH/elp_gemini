"""피드백 envelope → Markdown 렌더 (순수 함수, #156)."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from app.services.simulation import feedback

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "check_no_emojis_in_reports.py"
)


def _emoji_guard():
    spec = importlib.util.spec_from_file_location("emoji_guard", str(SCRIPT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _envelope(version=None):
    return {
        "feedback": {
            "risk_scenarios": [
                {
                    "title": "참여 편중 \U0001f525",
                    "scene": "활동1에서 한 학생이 질문을 독점할 수 있다.",
                    "evidence_type": "상호작용",
                }
            ],
            "utterance_suggestions": [
                {
                    "phase_idx": 1,
                    "actual": "질문해 보세요.",
                    "suggested": "한 사람씩 질문 1개씩 해 볼까요? ✅",
                    "intent": "발언 기회 분산",
                }
            ],
            "progress_directions": ["\U0001f449 활동2 전에 예시를 보여 준다."],
            "change_directions": [
                {"kind": "자료", "content": "반례 자료를 함께 제시한다."}
            ],
        },
        "model_name": "fake-model",
        "latency_ms": 8200,
        "guideline_version": version,
        "created_at": "2026-10-21T10:00:00",
    }


SESSION = SimpleNamespace(id=7)


def test_title_then_disclaimer_first_then_sections():
    md = feedback.render_markdown(
        _envelope(), SESSION, phase_names=["도입", "활동1"]
    )
    lines = md.splitlines()
    assert lines[0] == "# 수업 시뮬레이션 피드백(가설)"
    first_paragraph = next(line for line in lines[1:] if line.strip())
    assert first_paragraph == feedback.DISCLAIMER
    assert "fake-model" in md and "8.2" in md and "기본값" in md
    for heading in (
        "위험 시나리오",
        "교사 발화 추천",
        "진행 방향",
        "변경 방향",
    ):
        assert heading in md
    assert "활동1" in md  # 발화 추천의 장면 이름
    assert "질문해 보세요." in md and "발언 기회 분산" in md
    assert "반례 자료를 함께 제시한다." in md


def test_custom_guideline_version_is_shown():
    md = feedback.render_markdown(_envelope(version=3), SESSION)
    assert "커스텀 v3" in md


def test_emoji_in_model_text_is_stripped_and_guard_passes():
    md = feedback.render_markdown(_envelope(), SESSION)
    assert "참여 편중" in md
    assert "\U0001f525" not in md and "✅" not in md
    assert _emoji_guard()._scan_full(md.splitlines()) == []


def test_individual_support_section_lists_each_item():
    envelope = _envelope()
    envelope["feedback"]["individual_supports"] = [
        {
            "persona": "건우",
            "phase_idx": 1,
            "teacher_seq": 17,
            "actual": "건우야, 이 그림을 다시 볼래?",
            "what_worked": "짧게 답하던 건우가 이유를 말했다 \U0001f44d",
            "plan_suggestion": "활동1에 그림 다시 보기 발문을 넣는다.",
        }
    ]
    md = feedback.render_markdown(
        envelope, SESSION, phase_names=["도입", "활동1"]
    )
    assert "### 활동1 · 건우" in md
    assert "- 1:1 발화: 건우야, 이 그림을 다시 볼래?" in md
    assert "- 학생 반응 변화: 짧게 답하던 건우가 이유를 말했다" in md
    assert "- 지도안 반영: 활동1에 그림 다시 보기 발문을 넣는다." in md
    assert "\U0001f44d" not in md
    assert feedback.NO_SUPPORTS not in md
    assert _emoji_guard()._scan_full(md.splitlines()) == []


MULTILINE = "한 줄씩 읽어 볼까요?\n\n## 힌트\n첫 단어를 살펴보세요."
FOLDED = "한 줄씩 읽어 볼까요? ## 힌트 첫 단어를 살펴보세요."
SECTION_TITLES = [
    "## 위험 시나리오",
    "## ① 교사 발화 추천",
    "## ② 진행 방향",
    "## ③ 변경 방향",
    "## ④ 개별 지원",
]


def _section_lines(lines):
    return [line for line in lines if line.startswith("## ")]


def test_multiline_individual_support_stays_inside_its_section():
    envelope = _envelope()
    envelope["feedback"]["individual_supports"] = [
        {
            "persona": "건우",
            "phase_idx": 1,
            "teacher_seq": 17,
            "actual": MULTILINE,
            "what_worked": "짧게 답하던 건우가\n이유를 말했다",
            "plan_suggestion": "활동1에\n\n그림 다시 보기 발문을 넣는다.",
        }
    ]
    lines = feedback.render_markdown(
        envelope, SESSION, phase_names=["도입", "활동1"]
    ).splitlines()
    assert _section_lines(lines) == SECTION_TITLES
    assert f"- 1:1 발화: {FOLDED}" in lines
    assert "- 학생 반응 변화: 짧게 답하던 건우가 이유를 말했다" in lines
    assert "- 지도안 반영: 활동1에 그림 다시 보기 발문을 넣는다." in lines
    start = lines.index("## ④ 개별 지원")
    for prefix in ("- 학생 반응 변화:", "- 지도안 반영:"):
        assert any(line.startswith(prefix) for line in lines[start + 1 :])


def test_multiline_actual_utterance_stays_one_line():
    envelope = _envelope()
    envelope["feedback"]["utterance_suggestions"][0]["actual"] = MULTILINE
    lines = feedback.render_markdown(envelope, SESSION).splitlines()
    assert _section_lines(lines) == SECTION_TITLES
    assert f"- 실제 발화: {FOLDED}" in lines


def test_every_section_starts_with_hypothesis_note():
    lines = feedback.render_markdown(_envelope(), SESSION).splitlines()
    sections = [i for i, line in enumerate(lines) if line.startswith("## ")]
    # _envelope()에는 individual_supports가 없다: 옛 feedback_json 사례 (#395)
    assert len(sections) == 5
    assert lines[sections[-1]] == "## ④ 개별 지원"
    assert feedback.NO_SUPPORTS in lines
    for i in sections:
        following = next(line for line in lines[i + 1 :] if line.strip())
        assert following == feedback.SECTION_NOTE
    assert "가설이며 예측이 아닙니다" in feedback.SECTION_NOTE
