"""Gemini 응답 파싱 (#152): 깨진 JSON·스키마 불일치 → None."""

import pytest

from app.services.simulation.gemini import parse_structured
from app.services.simulation.llm_schemas import StudentReaction

GOOD = (
    '{"action": "손을 든다", "utterance": "저요!", "artifact": "",'
    ' "misconception": "", "ready_for_next": true, "confidence": 0.7}'
)


def test_valid_json_parses():
    parsed = parse_structured(StudentReaction, GOOD)
    assert parsed == StudentReaction(
        action="손을 든다",
        utterance="저요!",
        artifact="",
        misconception="",
        ready_for_next=True,
        confidence=0.7,
    )


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "",
        None,
        '{"action": "x"}',
        GOOD.replace('"ready_for_next": true', '"ready_for_next": "maybe"'),
    ],
)
def test_bad_json_or_wrong_fields_is_none(text):
    assert parse_structured(StudentReaction, text) is None
