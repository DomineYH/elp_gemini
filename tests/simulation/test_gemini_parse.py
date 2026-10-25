"""Gemini 응답 파싱 (#152), 클라이언트 timeout (#260), 클라이언트 수명 (#275)."""

import gc
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import settings
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


def test_client_is_created_with_timeout():
    # __wrapped__로 lru_cache를 거치지 않아 캐시를 오염시키지 않는다
    with patch.object(gemini.genai, "Client") as client:
        gemini._client.__wrapped__()
    opts = client.call_args.kwargs["http_options"]
    assert opts.api_version == "v1beta"
    assert opts.timeout == settings.GEMINI_HTTP_TIMEOUT_MS == 120_000


def test_uncached_client_stays_alive_during_call(monkeypatch):
    # 첫 호출 lru_cache 경합에서 진 스레드는 캐시되지 않은 Client를 받는다 (#275)
    api = SimpleNamespace(closed=False)

    class FakeModels:
        def generate_content(self, **kw):
            gc.collect()
            if api.closed:
                raise RuntimeError(
                    "Cannot send a request, as the client has been closed."
                )
            return SimpleNamespace(text=GOOD, parsed=None)

    class FakeClient:
        def __init__(self):
            self.models = FakeModels()

        def __del__(self):
            api.closed = True

    monkeypatch.setattr(gemini, "_client", lambda: FakeClient())

    result = gemini.call_structured(
        "student", system="sys", user="usr", schema=StudentReaction
    )

    assert result.parsed == parse_structured(StudentReaction, GOOD)
