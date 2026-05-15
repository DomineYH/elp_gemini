# tests/services/test_qna_criteria_citation_guard.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.app_state_repository import (
    SYNC_STATE_OK,
)


@pytest.mark.asyncio
async def test_qna_skips_criteria_citation_when_sync_not_ok():
    from app.services.criteria_context_service import (
        build_criteria_context_or_notice,
    )

    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value="needs_resync")
    criteria_ctx_svc = AsyncMock()

    ctx, notice = await build_criteria_context_or_notice(
        app_state_repo=app_state,
        criteria_context_service=criteria_ctx_svc,
        question="test question",
    )
    assert ctx is None
    assert notice == "평가기준 동기화가 필요합니다."


@pytest.mark.asyncio
async def test_qna_builds_normal_context_when_sync_ok():
    from app.services.criteria_context_service import (
        build_criteria_context_or_notice,
    )

    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value=SYNC_STATE_OK)
    criteria_ctx_svc = AsyncMock()
    criteria_ctx_svc.get_context = AsyncMock(return_value={
        "context_text": "some text",
        "criteria_ids": [1],
        "criteria_metadata": [],
        "citations": [],
    })

    ctx, notice = await build_criteria_context_or_notice(
        app_state_repo=app_state,
        criteria_context_service=criteria_ctx_svc,
        question="test question",
    )
    assert notice is None
    assert ctx is not None
    assert ctx["context_text"] == "some text"


@pytest.mark.asyncio
async def test_qna_uses_only_user_store_when_criteria_sync_not_ok():
    from app.services.qna_service import QnAService

    db = AsyncMock()
    client = MagicMock()
    response = MagicMock()
    response.text = "answer"
    response.candidates = []
    client.models.generate_content.return_value = response

    with patch(
        "app.services.qna_service.genai.Client", return_value=client
    ), patch(
        "app.services.qna_service.FileSearchService"
    ) as file_search_cls, patch(
        "app.services.criteria_context_service.build_criteria_context_or_notice",
        new=AsyncMock(return_value=(None, "평가기준 동기화가 필요합니다.")),
    ):
        file_search = file_search_cls.return_value
        file_search.get_user_store_id = MagicMock(
            return_value="fileSearchStores/user"
        )
        file_search.get_dual_store_ids = MagicMock(
            side_effect=AssertionError("rubric store must not be used")
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
    file_search_config = config.tools[0].file_search
    assert file_search_config.file_search_store_names == [
        "fileSearchStores/user"
    ]
    sent_contents = client.models.generate_content.call_args.kwargs["contents"]
    assert "평가기준 동기화가 필요합니다." in sent_contents
