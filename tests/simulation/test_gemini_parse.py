"""Gemini 응답 파싱 (#152): 깨진 JSON·스키마 불일치 → None."""

import logging
from types import SimpleNamespace

import pytest

from app.services.simulation import gemini
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


def test_rejected_output_logs_one_warning_without_raw_text(monkeypatch, caplog):
    raw = GOOD.replace('"ready_for_next": true', '"ready_for_next": "maybe"')
    response = SimpleNamespace(text=raw, parsed=None)
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kw: response)
    )
    monkeypatch.setattr(gemini, "_client", lambda: client)

    with caplog.at_level(logging.WARNING, logger=gemini.__name__):
        result = gemini.call_structured(
            "student",
            system="sys",
            user="usr",
            schema=StudentReaction,
            persona_key="42",
        )

    assert result.parsed is None
    [record] = [r for r in caplog.records if r.levelno == logging.WARNING]
    message = record.getMessage()
    assert "student" in message and "42" in message
    assert "ready_for_next" in message
    assert "maybe" not in message and raw not in message
