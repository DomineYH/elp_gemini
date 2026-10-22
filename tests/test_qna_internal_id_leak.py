"""
QnA가 File Search 내부 store id를 프롬프트·답변에 노출하지 않는다 (#174)

라이브 Gemini 검색 품질(평가성 질문 citations에 user store 청크 포함)은
이 테스트 범위가 아니다. 여기서는 모델에 보내는 contents·system prompt와
반환/저장되는 답변 문자열만 검사한다.
"""

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.lessonplan_analysis_service import (
    _LESSONPLAN_RETRIEVE_QUERY,
)
from app.services.prompt_loader_service import PromptLoaderService
from app.services.qna_service import QnAService, strip_internal_store_ids

USER_STORE = "fileSearchStores/user7store-0sjez5f0ga08"
RUBRIC_STORE = "fileSearchStores/rubricstore-k2j3h4g5f6d7"
LEAK_MARKERS = ("fileSearchStores/", "store-", "rubricstore", "user7store")


def _assert_no_leak(text):
    for marker in LEAK_MARKERS:
        assert marker not in text, (marker, text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "업로드하신 수업 지도안(user5store-0sjez5f0ga08) "
            "문서를 확인한 결과",
            "업로드하신 수업 지도안 문서를 확인한 결과",
        ),
        (
            "rubricstore를 참고하면 평가 계획이 부족합니다.",
            "평가기준 문서를 참고하면 평가 계획이 부족합니다.",
        ),
        (
            f"출처: {USER_STORE}/documents/lesson-pdf-abc",
            "출처: 업로드 문서",
        ),
        ("user-7-store 문서에 따르면", "업로드하신 지도안 문서에 따르면"),
        ("평가 계획 표가 있습니다.", "평가 계획 표가 있습니다."),
    ],
)
def test_strip_internal_store_ids(raw, expected):
    assert strip_internal_store_ids(raw) == expected


def test_strip_keeps_ordinary_words():
    text = "학생 활동(store 놀이)과 restore 단계, user 경험"
    assert strip_internal_store_ids(text) == text
    assert strip_internal_store_ids(None) is None
    assert strip_internal_store_ids("") == ""


def test_qna_and_analysis_prompts_have_no_store_identifiers():
    loader = PromptLoaderService()
    for name in ("qna", "lesson_analysis"):
        prompt = loader.get_prompt(name)
        for marker in ("rubricstore", "user{id}store", "fileSearchStores/"):
            assert marker not in prompt, (name, marker)
    assert "내부 식별자" in loader.get_prompt("qna")


def test_ask_question_no_longer_takes_client_store_id():
    """라우터가 URL 경로에서 뽑던 store_id는 쓰이지 않았고 제거됐다."""
    params = inspect.signature(QnAService.ask_question).parameters
    assert "store_id" not in params


def _grounded(title):
    chunk = SimpleNamespace(
        retrieved_context=SimpleNamespace(title=title, uri="u")
    )
    return [
        SimpleNamespace(
            grounding_metadata=SimpleNamespace(grounding_chunks=[chunk])
        )
    ]


async def _ask(
    question,
    model_answer,
    history=None,
    lesson_text=None,
    pass2_title=None,
    pass1_exc=None,
):
    db = AsyncMock()
    client = MagicMock()
    response = MagicMock()
    response.text = model_answer
    response.candidates = _grounded(pass2_title) if pass2_title else []
    if pass1_exc is not None:
        client.models.generate_content.side_effect = [pass1_exc, response]
    elif lesson_text is None:
        client.models.generate_content.return_value = response
    else:
        pass1 = MagicMock(text=lesson_text)
        pass1.candidates = _grounded("lesson.pdf")
        client.models.generate_content.side_effect = [pass1, response]

    with (
        patch("app.services.qna_service.genai.Client", return_value=client),
        patch("app.services.qna_service.FileSearchService") as fs_cls,
        patch(
            "app.services.criteria_context_service."
            "build_criteria_context_or_notice",
            new=AsyncMock(return_value=(None, None)),
        ),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="01HACTIVE"'),
            create=True,
        ),
    ):
        fs = fs_cls.return_value
        fs.get_user_store_id = MagicMock(return_value=USER_STORE)
        fs.get_dual_store_ids = MagicMock(
            return_value=[USER_STORE, RUBRIC_STORE]
        )
        service = QnAService(db)
        service._get_session = AsyncMock(
            return_value=SimpleNamespace(id=1, user_id=7)
        )
        service.prompt_loader.get_prompt = MagicMock(
            return_value=PromptLoaderService().get_prompt("qna")
        )
        service.get_conversation_history = AsyncMock(return_value=history or [])
        service._save_messages = AsyncMock()
        result = await service.ask_question(
            session_id=1, question=question, user_id=7, username="t"
        )
    return client, service, result


def _stores(kwargs):
    return [
        tool.file_search.file_search_store_names
        for tool in kwargs["config"].tools
    ]


@pytest.mark.asyncio
async def test_evaluation_question_hides_store_ids_and_searches_user_first():
    leaked = (
        "업로드하신 수업 지도안(user7store-0sjez5f0ga08) 문서를 확인한 결과, "
        "rubricstore 기준으로 평가 계획을 보완해야 합니다."
    )
    client, service, result = await _ask(
        "평가 계획의 보완점은 무엇인가요?",
        leaked,
        history=[{"question": "q", "answer": f"이전 답 {USER_STORE}"}],
        lesson_text="평가기준(상·중·하) 방법: 관찰",
    )

    calls = client.models.generate_content.call_args_list
    assert len(calls) == 2
    assert _stores(calls[0].kwargs) == [[USER_STORE]]
    assert calls[0].kwargs["contents"] == _LESSONPLAN_RETRIEVE_QUERY

    kwargs = calls[1].kwargs
    _assert_no_leak(kwargs["contents"])
    _assert_no_leak(kwargs["config"].system_instruction)
    assert "관찰" in kwargs["contents"]

    assert _stores(kwargs) == [[RUBRIC_STORE]]
    rubric_tool = kwargs["config"].tools[0]
    assert rubric_tool.file_search.metadata_filter == 'stable_id="01HACTIVE"'

    _assert_no_leak(result["answer"])
    assert "평가 계획을 보완해야 합니다" in result["answer"]
    saved = service._save_messages.await_args.kwargs["answer"]
    _assert_no_leak(saved)


@pytest.mark.asyncio
async def test_content_question_hides_store_ids():
    client, _, result = await _ask(
        "이 지도안의 학습 목표는 무엇인가요?",
        f"{USER_STORE} 문서의 학습 목표는 분수 이해입니다.",
    )
    assert client.models.generate_content.call_count == 1
    kwargs = client.models.generate_content.call_args.kwargs
    _assert_no_leak(kwargs["contents"])
    stores = [
        tool.file_search.file_search_store_names
        for tool in kwargs["config"].tools
    ]
    assert stores == [[USER_STORE]]
    _assert_no_leak(result["answer"])
    assert "학습 목표는 분수 이해입니다" in result["answer"]


def _titles(citations):
    return [
        chunk["retrieved_context"]["title"]
        for chunk in citations["grounding_chunks"]
    ]


@pytest.mark.asyncio
async def test_evaluation_citations_include_pass1_user_chunks():
    client, service, result = await _ask(
        "평가 계획의 보완점은 무엇인가요?",
        "관찰 평가를 보완하세요.",
        lesson_text="평가기준(상·중·하) 방법: 관찰",
        pass2_title="rubric.pdf",
    )
    assert client.models.generate_content.call_count == 2
    # 1패스 청크는 뒤에 붙인다: grounding_supports 인덱스 유지
    assert _titles(result["citations"]) == ["rubric.pdf", "lesson.pdf"]
    saved = service._save_messages.await_args.kwargs["citations"]
    assert "lesson.pdf" in _titles(saved["documents"])
    assert result["grounding_metadata"]["sources_count"] == 2


@pytest.mark.asyncio
async def test_evaluation_keeps_pass1_chunks_without_pass2_grounding():
    _, _, result = await _ask(
        "평가 계획의 보완점은 무엇인가요?",
        "관찰 평가를 보완하세요.",
        lesson_text="평가기준(상·중·하) 방법: 관찰",
    )
    assert _titles(result["citations"]) == ["lesson.pdf"]
    assert result["grounding_metadata"]["sources_count"] == 1


@pytest.mark.asyncio
async def test_evaluation_falls_back_to_dual_tools_when_pass1_empty():
    client, _, _ = await _ask(
        "평가 계획의 보완점은 무엇인가요?",
        "보완점입니다.",
        lesson_text="",
    )
    calls = client.models.generate_content.call_args_list
    assert len(calls) == 2
    assert _stores(calls[1].kwargs) == [[USER_STORE], [RUBRIC_STORE]]


@pytest.mark.asyncio
async def test_evaluation_falls_back_to_dual_tools_when_pass1_raises():
    client, _, result = await _ask(
        "평가 계획의 보완점은 무엇인가요?",
        "보완점입니다.",
        pass1_exc=RuntimeError("file search down"),
    )
    calls = client.models.generate_content.call_args_list
    assert len(calls) == 2
    assert _stores(calls[1].kwargs) == [[USER_STORE], [RUBRIC_STORE]]
    assert "보완점입니다" in result["answer"]
