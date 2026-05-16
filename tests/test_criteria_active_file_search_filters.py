"""Active criteria metadata filters for rubric File Search call sites."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _file_search_for_store(config, store_name: str):
    for tool in config.tools:
        file_search = tool.file_search
        if file_search.file_search_store_names == [store_name]:
            return file_search
    return None


def test_lessonplan_file_search_filters_only_rubric_store():
    from app.services.lessonplan_analysis_service import (
        _call_gemini_with_file_search,
    )

    client = MagicMock()
    response = SimpleNamespace(text="report", candidates=[])
    client.models.generate_content.return_value = response

    result = _call_gemini_with_file_search(
        client,
        "gemini-eval",
        "contents",
        "fileSearchStores/rubric",
        "fileSearchStores/user",
        'stable_id="01HACTIVE"',
    )

    assert result is response
    config = client.models.generate_content.call_args.kwargs["config"]
    rubric_search = _file_search_for_store(config, "fileSearchStores/rubric")
    user_search = _file_search_for_store(config, "fileSearchStores/user")

    assert rubric_search is not None
    assert rubric_search.metadata_filter == 'stable_id="01HACTIVE"'
    assert user_search is not None
    assert getattr(user_search, "metadata_filter", None) is None


@pytest.mark.asyncio
async def test_lessonplan_analysis_skips_gemini_when_no_active_criteria():
    from app.services.lessonplan_analysis_service import (
        LessonPlanAnalysisService,
    )

    db = AsyncMock()
    client = MagicMock()

    with patch(
        "app.services.lessonplan_analysis_service.genai.Client",
        return_value=client,
    ), patch(
        "app.services.lessonplan_analysis_service.FileSearchService"
    ):
        service = LessonPlanAnalysisService(db)

    service._find_existing_report_for_latest_upload = AsyncMock(
        return_value=(
            SimpleNamespace(
                id=11,
                filename="lesson.pdf",
                original_filename="lesson.pdf",
            ),
            None,
        )
    )
    service._get_store_ids = AsyncMock(
        return_value=["fileSearchStores/user", "fileSearchStores/rubric"]
    )
    service.prompt_loader.get_prompt = MagicMock(return_value="{model_name}")
    service.report_storage.save_report = MagicMock(
        return_value={"filename": "report.md", "file_path": "/tmp/report.md"}
    )

    with patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value=None),
        create=True,
    ), patch(
        "app.services.lessonplan_analysis_service._call_gemini_with_file_search",
        return_value=SimpleNamespace(text="report", candidates=[]),
    ) as gemini_call:
        result = await service.analyze_lesson_plan(
            session_id=1,
            user_id=7,
            username="teacher",
        )

    assert result["success"] is False
    assert result["error_code"] == "NO_ACTIVE_CRITERIA"
    gemini_call.assert_not_called()


@pytest.mark.asyncio
async def test_qna_evaluation_filters_rubric_store_by_active_stable_id():
    from app.services.qna_service import QnAService

    db = AsyncMock()
    client = MagicMock()
    response = MagicMock()
    response.text = "answer"
    response.candidates = []
    client.models.generate_content.return_value = response

    with patch(
        "app.services.qna_service.genai.Client",
        return_value=client,
    ), patch(
        "app.services.qna_service.FileSearchService"
    ) as file_search_cls, patch(
        "app.services.criteria_context_service.build_criteria_context_or_notice",
        new=AsyncMock(return_value=(None, None)),
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="01HACTIVE"'),
        create=True,
    ):
        file_search = file_search_cls.return_value
        file_search.get_user_store_id = MagicMock(
            return_value="fileSearchStores/user"
        )
        file_search.get_dual_store_ids = MagicMock(
            return_value=["fileSearchStores/user", "fileSearchStores/rubric"]
        )

        service = QnAService(db)
        service._get_session = AsyncMock(
            return_value=SimpleNamespace(id=1, user_id=7)
        )
        service.prompt_loader.get_prompt = MagicMock(return_value="system")
        service.get_conversation_history = AsyncMock(return_value=[])
        service._save_messages = AsyncMock()

        await service.ask_question(
            session_id=1,
            question="이 수업을 평가해줘",
            user_id=7,
            username="teacher",
        )

    config = client.models.generate_content.call_args.kwargs["config"]
    rubric_search = _file_search_for_store(config, "fileSearchStores/rubric")
    user_search = _file_search_for_store(config, "fileSearchStores/user")

    assert rubric_search is not None
    assert rubric_search.metadata_filter == 'stable_id="01HACTIVE"'
    assert user_search is not None
    assert getattr(user_search, "metadata_filter", None) is None


@pytest.mark.asyncio
async def test_qna_evaluation_skips_rubric_store_when_no_active_criteria():
    from app.services.qna_service import QnAService

    db = AsyncMock()
    client = MagicMock()
    response = MagicMock()
    response.text = "answer"
    response.candidates = []
    client.models.generate_content.return_value = response

    with patch(
        "app.services.qna_service.genai.Client",
        return_value=client,
    ), patch(
        "app.services.qna_service.FileSearchService"
    ) as file_search_cls, patch(
        "app.services.criteria_context_service.build_criteria_context_or_notice",
        new=AsyncMock(return_value=(None, None)),
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value=None),
        create=True,
    ):
        file_search = file_search_cls.return_value
        file_search.get_user_store_id = MagicMock(
            return_value="fileSearchStores/user"
        )
        file_search.get_dual_store_ids = MagicMock(
            return_value=["fileSearchStores/user", "fileSearchStores/rubric"]
        )

        service = QnAService(db)
        service._get_session = AsyncMock(
            return_value=SimpleNamespace(id=1, user_id=7)
        )
        service.prompt_loader.get_prompt = MagicMock(return_value="system")
        service.get_conversation_history = AsyncMock(return_value=[])
        service._save_messages = AsyncMock()

        await service.ask_question(
            session_id=1,
            question="이 수업을 평가해줘",
            user_id=7,
            username="teacher",
        )

    config = client.models.generate_content.call_args.kwargs["config"]
    all_store_names = [
        name
        for tool in config.tools
        for name in tool.file_search.file_search_store_names
    ]

    assert all_store_names == ["fileSearchStores/user"]
    sent_contents = client.models.generate_content.call_args.kwargs["contents"]
    assert "활성 평가기준이 없습니다" in sent_contents
