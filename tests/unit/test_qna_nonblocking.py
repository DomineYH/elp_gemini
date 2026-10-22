"""동기 Gemini 호출이 event loop를 막지 않고 timeout을 갖는다 (#218)"""

import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.config import settings
from app.services import eval_service, file_search_service, qna_service
from app.services.eval_service import EvaluationService
from app.services.file_search_service import FileSearchService
from app.services.lessonplan_analysis_service import LessonPlanAnalysisService
from app.services.qna_service import QnAService


def _slow_response(*args, **kwargs):
    time.sleep(0.5)
    response = Mock()
    response.text = "답변"
    response.candidates = []
    return response


def _slow(value):
    """0.5초 막은 뒤 value를 돌려주는 동기 SDK 호출 목"""

    def call(*args, **kwargs):
        time.sleep(0.5)
        return value

    return Mock(side_effect=call)


async def _ticks_while(coro):
    """coro가 도는 동안 0.05초 ticker가 몇 번 돌았는지 센다."""
    ticks = 0
    done = False

    async def run():
        nonlocal done
        try:
            return await coro
        finally:
            done = True

    async def ticker():
        nonlocal ticks
        while not done:
            await asyncio.sleep(0.05)
            ticks += 1

    result, _ = await asyncio.gather(run(), ticker())
    return result, ticks


@pytest.mark.asyncio
async def test_qna_ask_question_does_not_block_loop():
    with (
        patch.object(qna_service.genai, "Client"),
        patch.object(qna_service, "FileSearchService"),
        patch.object(qna_service, "PromptLoaderService"),
    ):
        service = QnAService(AsyncMock())
    service._get_session = AsyncMock(return_value=Mock(title="t"))
    service.prompt_loader.get_prompt = Mock(return_value="prompt")
    service.get_conversation_history = AsyncMock(return_value=[])
    service.file_search_service.get_user_store_id = Mock(
        return_value="fileSearchStores/u1"
    )
    service._save_messages = AsyncMock()
    service.client.models.generate_content = Mock(side_effect=_slow_response)

    with patch(
        "app.services.criteria_context_service."
        "build_criteria_context_or_notice",
        AsyncMock(return_value=(None, None)),
    ):
        result, ticks = await _ticks_while(
            service.ask_question(
                session_id=1,
                question="학습 목표를 요약해 줘",
                user_id=1,
                username="u",
            )
        )

    assert result["answer"] == "답변"
    assert ticks >= 5


@pytest.mark.asyncio
async def test_execute_evaluation_does_not_block_loop():
    service = EvaluationService.__new__(EvaluationService)
    service.eval_model_name = "m"
    service.client = Mock()
    service.client.models.generate_content = Mock(side_effect=_slow_response)
    service.prompt_builder = Mock()
    service.prompt_builder.parse_evaluation_response = Mock(
        return_value={"ok": True}
    )

    result, ticks = await _ticks_while(service._execute_evaluation("prompt"))

    assert result == {"ok": True}
    assert ticks >= 5


@pytest.mark.asyncio
async def test_search_in_store_does_not_block_loop():
    service = FileSearchService.__new__(FileSearchService)
    service.client = Mock()
    service.client.models.generate_content = Mock(side_effect=_slow_response)
    service._extract_citations = Mock(return_value=[])

    result, ticks = await _ticks_while(
        service.search_in_store("q", "fileSearchStores/u1")
    )

    assert result["response_text"] == "답변"
    assert ticks >= 5


@pytest.mark.asyncio
async def test_upload_document_store_lookup_does_not_block_loop(tmp_path):
    service = FileSearchService.__new__(FileSearchService)
    service.client = Mock()
    service.main_store_name = "main"
    service._get_or_create_store = _slow(Mock(name="store"))
    operation = Mock(done=True)
    operation.response.document_name = "fileSearchStores/u1/documents/d1"
    operation.response.parent = "fileSearchStores/u1"
    service.client.file_search_stores.upload_to_file_search_store = Mock(
        return_value=operation
    )
    file_path = tmp_path / "plan.txt"
    file_path.write_text("x")

    result, ticks = await _ticks_while(
        service.upload_document(str(file_path), "plan.txt", {"user_id": 1})
    )

    assert result == {
        "document_id": "fileSearchStores/u1/documents/d1",
        "store_id": "fileSearchStores/u1",
    }
    assert ticks >= 5


@pytest.mark.asyncio
async def test_qna_store_lookup_does_not_block_loop():
    with (
        patch.object(qna_service.genai, "Client"),
        patch.object(qna_service, "FileSearchService"),
        patch.object(qna_service, "PromptLoaderService"),
    ):
        service = QnAService(AsyncMock())
    service._get_session = AsyncMock(return_value=Mock(title="t"))
    service.prompt_loader.get_prompt = Mock(return_value="prompt")
    service.get_conversation_history = AsyncMock(return_value=[])
    service.file_search_service.get_user_store_id = _slow("fileSearchStores/u1")
    service._save_messages = AsyncMock()
    response = Mock(text="답변", candidates=[])
    service.client.models.generate_content = Mock(return_value=response)

    with patch(
        "app.services.criteria_context_service."
        "build_criteria_context_or_notice",
        AsyncMock(return_value=(None, None)),
    ):
        result, ticks = await _ticks_while(
            service.ask_question(
                session_id=1,
                question="학습 목표를 요약해 줘",
                user_id=1,
                username="u",
            )
        )

    assert result["answer"] == "답변"
    assert ticks >= 5


@pytest.mark.asyncio
async def test_delete_store_by_display_name_does_not_block_loop():
    service = FileSearchService.__new__(FileSearchService)
    service.client = Mock()
    service.client.file_search_stores.list = _slow([])

    result, ticks = await _ticks_while(
        service.delete_store_by_display_name("user-1-store")
    )

    assert result is None
    service.client.file_search_stores.list.assert_called_once()
    assert ticks >= 5


@pytest.mark.asyncio
async def test_analysis_get_store_ids_does_not_block_loop():
    service = LessonPlanAnalysisService.__new__(LessonPlanAnalysisService)
    service.file_search_service = Mock()
    store_ids = ["fileSearchStores/u1", "fileSearchStores/rubric"]
    service.file_search_service.get_dual_store_ids = _slow(store_ids)

    result, ticks = await _ticks_while(service._get_store_ids(1))

    assert result == store_ids
    assert ticks >= 5


def _timeout_of(client_cls):
    http_options = client_cls.call_args.kwargs["http_options"]
    assert http_options.api_version == "v1beta"
    return http_options.timeout


def test_gemini_clients_are_created_with_timeout(monkeypatch):
    expected = settings.GEMINI_HTTP_TIMEOUT_MS
    assert expected == 120_000

    with (
        patch.object(qna_service.genai, "Client") as client,
        patch.object(qna_service, "FileSearchService"),
        patch.object(qna_service, "PromptLoaderService"),
    ):
        QnAService(AsyncMock())
    assert _timeout_of(client) == expected

    with (
        patch.object(eval_service.genai, "Client") as client,
        patch.object(eval_service, "AnalysisStorageService"),
        patch.object(eval_service, "CriteriaVectorService"),
        patch.object(eval_service, "PromptLoaderService"),
        patch.object(eval_service, "EvaluationPromptBuilder"),
    ):
        EvaluationService()
    assert _timeout_of(client) == expected

    monkeypatch.setattr(FileSearchService, "_client", None)
    with patch.object(file_search_service.genai, "Client") as client:
        FileSearchService.get_client()
    assert _timeout_of(client) == expected
