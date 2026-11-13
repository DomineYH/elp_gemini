"""Gemini 응답 파싱 (#152), 클라이언트 timeout (#260), 클라이언트 수명 (#275)."""

import gc
import json
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


# 세션 16 seq 21 원문 (#341)
S16_21 = (
    "머신러닝 기법과 회귀계수 등의 개념을 이해하지 못해 멍해졌으며 "
    "과업 범위를 넘어선 통계적 개념에 혼란을 겪고 있다."
)


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
        ("비율이 인원수로 여겨질 수 있다", 85, "", 79),
        ("비율이 인원수로 받아들여질 수 있다", 85, "", 79),
        # '볼 수 있다'는 '거꾸로 볼'처럼 실제 생각일 수 있어 남긴다
        ("비율을 인원수로 볼 수 있다", 85, "비율을 인원수로 볼 수 있다", 79),
        (
            "비율을 인원수라고 볼 수 있다",
            85,
            "비율을 인원수라고 볼 수 있다",
            79,
        ),
        (
            "인원수가 늘어난다고 볼 수 있다",
            85,
            "인원수가 늘어난다고 볼 수 있다",
            79,
        ),
        (
            "분수는 역수와 같으므로 거꾸로 볼 수 있다",
            85,
            "분수는 역수와 같으므로 거꾸로 볼 수 있다",
            79,
        ),
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
        # '혼란을 겪고 있다'류 끝말도 막힘이다 (#341)
        (S16_21, 45, "", 45),
        (S16_21, 85, "", 79),
        ("통계 용어 때문에 혼란을 겪음", 85, "", 79),
        ("통계 용어 때문에 혼란을 겪는다.", 85, "", 79),
        ("통계 용어 때문에 혼란을 겪고있음", 85, "", 79),
        (
            "혼란을 겪는다는 말을 틀리게 이해함",
            95,
            "혼란을 겪는다는 말을 틀리게 이해함",
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


MISC = "비율이 늘면 전체 사람 수도 늘어난다고 생각함"
# 세션 16 seq 13·18과 live 재현 형태 (#341)
F1 = (
    "선생님, 6학년 수준에서 다루기에는 선형회귀의 회귀계수 추정이나 외삽 오차 같은 "
    "개념이 조금 생소한 것 같습니다. 혹시 초등학생 눈높이에 맞춰서 어떤 방식으로 "
    "예측을 진행하게 되는지 조금 더 쉽게 설명해 주실 수 있나요?"
)
F2 = (
    "선생님, 다중공선성이나 명분할 오류 같은 단어들은 중학교나 고등학교 수학에서도 "
    "어려운 내용 같은데요. 저희가 오늘 실제로 엑셀이나 엔트리로 그래프를 그릴 때 "
    "이 복잡한 계산을 전부 다 직접 해야 하는 건가요?"
)
F4 = "저희가 이걸 다 이해해야 하는 건가요? 중학교 내용이라고 하셨는데, 조금 걱정되네요..."
F5 = (
    "저... 갑자기 어려운 단어들이 많이 나와서 잘 이해가 안 가요. "
    "2050년 미래를 예측할 때 오차가 커진다는 말씀인가요?"
)
# 산출물이 있으면 검증기는 남긴다(직전 산출물은 session_service가 본다)
F6_LIKE = "저... 더 어렵게 느껴져요. 그렇게 복잡한 과정인가요?"


@pytest.mark.parametrize(
    "utterance, artifact, raw, kept, expected",
    [
        ("잘 모르겠어요...", "", 30, "", 30),
        ("피자... 조각이요...? 잘 모르겠어요...", "", 30, "", 30),
        ("어... 인구수가 늘어나는 게... 아니에요...?", "", 30, "", 30),
        ("비율이 커지면 사람 수도 늘어나요.", "", 30, MISC, 30),
        ("잘 모르겠어요. 근데 분모끼리 더하면 돼요.", "", 30, MISC, 30),
        ("잘 모르겠어요.", "32명 - 22명 = 10명 감소", 30, MISC, 30),
        ("많이 연습해서요...", "", 30, MISC, 30),
        ("", "", 30, "", 30),
        ("잘 모르겠어요...", "", 90, "", 79),
        ("아니에요?!", "", 30, "", 30),
        ("잘 모르겠어요\n분모끼리 더하면 돼요", "", 30, MISC, 30),
        # 질문과 함께 나온 난이도·걱정 문장도 막힘이다 (#341)
        (F1, "", 30, "", 30),
        (F2, "", 30, "", 30),
        (F4, "", 30, "", 30),
        (F5, "", 30, "", 30),
        (
            "지구가 태양보다 크잖아요. 그럼 태양이 지구를 도는 건가요?",
            "",
            30,
            MISC,
            30,
        ),
        ("분모끼리 더하면 돼요. 맞죠?", "", 30, MISC, 30),
        ("너무 어려워요.", "", 30, MISC, 30),
        ("분수는 어려워서 그냥 분모끼리 더했어요.", "", 30, MISC, 30),
        (F6_LIKE, "32명 - 22명 = 10명 감소", 30, MISC, 30),
    ],
)
def test_stuck_only_reaction_has_no_misconception(
    utterance, artifact, raw, kept, expected
):
    """질문·'모르겠어요'만 있고 산출물이 없으면 오개념을 비운다. 79 상한은 먼저 (#330)."""
    data = json.loads(GOOD) | {
        "utterance": utterance,
        "artifact": artifact,
        "misconception": MISC,
        "understanding": raw,
    }
    parsed = parse_structured(
        StudentReaction, json.dumps(data, ensure_ascii=False)
    )
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
