# tests/services/test_qna_criteria_citation_guard.py
from unittest.mock import AsyncMock

import pytest

from app.repositories.app_state_repository import (
    KEY_SYNC_STATE,
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
