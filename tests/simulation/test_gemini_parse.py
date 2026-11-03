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
    ' "misconception": "", "ready_for_next": true, "understanding": 85,'
    ' "confidence": 0.7}'
)


def test_valid_json_parses():
    parsed = parse_structured(StudentReaction, GOOD)
    assert parsed == StudentReaction(
        action="손을 든다",
        utterance="저요!",
        artifact="",
        misconception="",
        ready_for_next=True,
        understanding=85,
        confidence=0.7,
    )


@pytest.mark.parametrize("raw, expected", [(150, 100), (-5, 0), (80, 80)])
def test_understanding_is_clamped(raw, expected):
    text = GOOD.replace('"understanding": 85', f'"understanding": {raw}')
    assert parse_structured(StudentReaction, text).understanding == expected


def test_missing_understanding_fails_parse():
    text = GOOD.replace(' "understanding": 85,', "")
    assert "understanding" not in text
    assert parse_structured(StudentReaction, text) is None


@pytest.mark.parametrize(
    "misconception, raw, expected", [("x", 95, 79), ("x", 60, 60), ("", 95, 95)]
)
def test_misconception_caps_understanding(misconception, raw, expected):
    text = GOOD.replace(
        '"misconception": ""', f'"misconception": "{misconception}"'
    ).replace('"understanding": 85', f'"understanding": {raw}')
    assert parse_structured(StudentReaction, text).understanding == expected


@pytest.mark.parametrize(
    "misconception, raw, kept, expected",
    [
        (
            "과거와 현재의 학교 모습 비교를 어떻게 시작해야 할지 모름",
            85,
            "",
            79,
        ),
        (
            "엑셀 파일을 여는 방법이나 첫 줄의 제목을 확인하는 방법을 모르고 막혀 있음",
            60,
            "",
            60,
        ),
        (
            "인구 그래프를 그리는 과업 도중에 급식 이야기로 주제가 바뀌어"
            " 과업 범위를 헷갈림.",
            90,
            "",
            79,
        ),
        ("분모끼리 더함", 95, "분모끼리 더함", 79),
        ("모름이라는 단어를 잘못 씀", 95, "모름이라는 단어를 잘못 씀", 79),
        ("그래프를 그리지 못함 ", 85, "", 79),
        ("표를 읽지 못함", 85, "", 79),
        ("순서를 헷갈려함", 85, "", 79),
        # '-다' 평서형 끝도 막힘 요약이다 (#305): live 원문 5건
        ("과거와 현재의 학교 모습을 비교하는 방법을 아직 모른다.", 85, "", 79),
        ("과거와 현재의 학교 모습을 비교하는 방법을 모르고 있다.", 85, "", 79),
        ("2006년 학급 소개판에서 인원수를 찾는 방법을 모른다.", 85, "", 79),
        (
            "엔트리나 이지통계 프로그램을 사용하여 인구 구성 데이터를"
            " 그래프로 변환하는 방법을 모른다.",
            85,
            "",
            79,
        ),
        (
            "엔트리에서 그래프를 생성하는 구체적인 메뉴 위치를 헷갈리고 있다.",
            85,
            "",
            79,
        ),
        ("표 읽는 법을 모르고있다", 85, "", 79),
        ("무엇을 써야 할지 모르겠다. ", 85, "", 79),
        ("무엇을 써야 할지 모르겠음", 85, "", 79),
        ("단위를 헷갈린다.", 85, "", 79),
        ("단위를 헷갈리고있다", 85, "", 79),
        ("단위를 헷갈려 한다.", 85, "", 79),
        ("단위를 헷갈려한다", 85, "", 79),
        ("첫 단계에서 막혔다.", 85, "", 79),
        ("첫 단계에서 막혀 있다.", 85, "", 79),
        ("첫 단계에서 막혀있다", 85, "", 79),
        ("그래프를 그리지 못한다.", 85, "", 79),
        ("그래프를 그리지 못 한다", 85, "", 79),
        (
            "모른다고 생각해서 분모를 더함",
            95,
            "모른다고 생각해서 분모를 더함",
            79,
        ),
        (
            "막혀 있다는 말을 틀리게 이해함",
            95,
            "막혀 있다는 말을 틀리게 이해함",
            79,
        ),
    ],
)
def test_stuck_summary_is_not_a_misconception(
    misconception, raw, kept, expected
):
    """'모름·막힘'은 오개념이 아니다: 79 상한은 원문 기준, 텍스트는 비운다 (#302)."""
    text = GOOD.replace(
        '"misconception": ""', f'"misconception": "{misconception}"'
    ).replace('"understanding": 85', f'"understanding": {raw}')
    parsed = parse_structured(StudentReaction, text)
    assert (parsed.misconception, parsed.understanding) == (kept, expected)


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
