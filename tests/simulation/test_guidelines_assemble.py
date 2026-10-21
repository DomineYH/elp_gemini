"""피드백 지침 조립 규칙 (#159, 순수 함수)."""

from types import SimpleNamespace

from app.services.simulation import guidelines

BASE = "기본 피드백 프롬프트 본문"


def _guideline(enabled):
    return SimpleNamespace(
        enabled=enabled,
        required_aspects=["udl", "question_types"],
        criteria_ids=[1],
        extra_instructions="협동학습 장면을 꼭 짚어 주세요.",
    )


def test_no_guideline_is_base_then_constraints():
    out = guidelines.assemble(BASE, None, ["평가기준 발췌"])
    assert out.startswith(BASE)
    assert out.endswith(guidelines.BASE_CONSTRAINTS)
    assert "평가기준 발췌" not in out


def test_disabled_guideline_equals_default():
    off = guidelines.assemble(BASE, _guideline(False), ["평가기준 발췌"])
    assert off == guidelines.assemble(BASE, None, [])


def test_enabled_guideline_adds_aspects_excerpts_and_extra():
    on = guidelines.assemble(BASE, _guideline(True), ["평가기준 발췌"])
    assert on.startswith(BASE)
    assert "UDL" in on
    assert "발문 유형" in on
    assert "평가기준 발췌" in on
    assert "협동학습 장면을 꼭 짚어 주세요." in on
    assert on.endswith(guidelines.BASE_CONSTRAINTS)
    assert on != guidelines.assemble(BASE, None, [])
