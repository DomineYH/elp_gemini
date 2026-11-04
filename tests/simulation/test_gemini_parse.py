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
    ' "confidence": 0.7, "on_task": true}'
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
        on_task=True,
    )


@pytest.mark.parametrize("raw, expected", [(150, 100), (-5, 0), (80, 80)])
def test_understanding_is_clamped(raw, expected):
    text = GOOD.replace('"understanding": 85', f'"understanding": {raw}')
    assert parse_structured(StudentReaction, text).understanding == expected


def test_missing_understanding_fails_parse():
    text = GOOD.replace(' "understanding": 85,', "")
    assert "understanding" not in text
    assert parse_structured(StudentReaction, text) is None


def test_on_task_is_required():
    """곁가지 반응 표시 (#306): 기본값이 있으면 SDK가 선택 항목으로 보내 모델이 빠뜨린다."""
    assert "on_task" in StudentReaction.model_json_schema()["required"]
    missing = GOOD.replace(', "on_task": true', "")
    assert "on_task" not in missing
    assert parse_structured(StudentReaction, missing) is None
    text = GOOD.replace('"on_task": true', '"on_task": false')
    assert parse_structured(StudentReaction, text).on_task is False


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
        # 못 하다 계열의 '-고 있다/-했다/-겠다' 끝 (#311): live 원문 포함
        (
            "인구 데이터에서 어떤 열이 불필요한지 판단하지 못하고 있다",
            30,
            "",
            30,
        ),
        (
            "인구 데이터에서 어떤 열이 불필요한지 판단하지 못하고 있다",
            85,
            "",
            79,
        ),
        ("그래프를 그리지 못하고 있음", 85, "", 79),
        ("그래프를 그리지 못 하고 있다", 85, "", 79),
        ("그래프를 그리지 못했다.", 85, "", 79),
        ("그래프를 그리지 못했음", 85, "", 79),
        ("그래프를 그리지 못하겠다 ", 85, "", 79),
        ("그래프를 그리지 못하겠음", 85, "", 79),
        # '잘못함/잘못했다'는 틀린 행동 서술이라 남긴다 (#311)
        ("분수 계산을 잘못함", 95, "분수 계산을 잘못함", 79),
        ("분수 계산을 잘못했다", 95, "분수 계산을 잘못했다", 79),
        (
            "못하고 있다는 말을 틀리게 이해함",
            95,
            "못하고 있다는 말을 틀리게 이해함",
            79,
        ),
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
        # 혼란·머뭇거림·망설임 요약 (#320): live 원문 포함
        (
            "이전 활동과 학습 목표의 연계를 파악하지 못하고 혼란스러워함",
            85,
            "",
            79,
        ),
        (
            "인구 구성비의 개념을 어렴풋이 짐작하지만 구체적으로 설명하지 못하고"
            " 머뭇거린다.",
            85,
            "",
            79,
        ),
        ("과업 순서가 혼란스럽다.", 85, "", 79),
        ("과업 순서에 대한 혼란스러움 ", 85, "", 79),
        ("과업 순서를 혼란스러워한다", 85, "", 79),
        ("과업 순서를 혼란스러워 하고 있다.", 85, "", 79),
        ("답을 말하기 전에 머뭇거림", 85, "", 79),
        ("답을 말하기 전에 머뭇거리고있음", 85, "", 79),
        ("발표를 망설임.", 85, "", 79),
        ("발표를 망설인다", 85, "", 79),
        ("발표를 망설이고 있다 ", 85, "", 79),
        # 추측으로 쓴 문장은 오개념이 아니다 (#317): live 원문 포함
        (
            "65세 이상 비율이 늘어난다는 것을 전체 인구가 늘어난다는 뜻으로"
            " 오해할 수 있다.",
            85,
            "",
            79,
        ),
        ("비율을 인원수로 읽을 것 같다.", 85, "", 79),
        ("비율을 인원수로 읽을것같음", 85, "", 79),
        ("비율을 인원수로 읽을 가능성이 있다", 85, "", 79),
        ("비율을 인원수로 읽을 가능성이 높음.", 85, "", 79),
        ("비율을 인원수로 읽을 우려가 있다 ", 85, "", 79),
        ("비율을 인원수라고 착각할 수 있음", 85, "", 79),
        ("비율과 인원수를 혼동할 수 있다.", 85, "", 79),
        ("비율이 곧 인원수라고 생각할 수 있다", 85, "", 79),
        ("비율을 인원수로 여길 수 있다", 85, "", 79),
        ("비율을 인원수로 받아들일수있음 ", 85, "", 79),
        ("비율을 인원수로 볼 수 있다", 85, "", 79),
        ("비율이 인원수로 여겨질 수 있다", 85, "", 79),
        ("비율이 인원수로 받아들여질 수 있다", 85, "", 79),
        ("인원수가 늘어난다고 볼 수 있다", 85, "", 79),
        # 보조동사 '-어 볼'은 인지 동사가 아니다
        (
            "모든 수를 0으로 나눠볼 수 있다",
            85,
            "모든 수를 0으로 나눠볼 수 있다",
            79,
        ),
        ("분모끼리 더해볼 수 있다", 85, "분모끼리 더해볼 수 있다", 79),
        ("먼저 더하고 볼 수 있다", 85, "먼저 더하고 볼 수 있다", 79),
        (
            "모든 수를 0으로 나눠 볼 수 있다",
            85,
            "모든 수를 0으로 나눠 볼 수 있다",
            79,
        ),
        # 인지 동사가 아닌 '…ㄹ 수 있다'는 학생의 단정일 수 있으니 남긴다 (#317)
        (
            "모든 수는 0으로 나눌 수 있다",
            85,
            "모든 수는 0으로 나눌 수 있다",
            79,
        ),
        ("분모끼리 더할 수 있다", 85, "분모끼리 더할 수 있다", 79),
        ("전체 인구가 늘 수 있음", 85, "전체 인구가 늘 수 있음", 79),
        # 실제 틀린 생각과 어미를 '말'로 다루는 문장은 남긴다 (#317, #320)
        (
            "분모끼리 더할 수 있다고 생각함",
            95,
            "분모끼리 더할 수 있다고 생각함",
            79,
        ),
        (
            "할 수 있다는 말을 틀리게 이해함",
            95,
            "할 수 있다는 말을 틀리게 이해함",
            79,
        ),
        (
            "혼란이라는 말을 틀리게 이해함",
            95,
            "혼란이라는 말을 틀리게 이해함",
            79,
        ),
        (
            "머뭇거린다는 말을 틀리게 이해함",
            95,
            "머뭇거린다는 말을 틀리게 이해함",
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
