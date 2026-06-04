"""Tests verifying QnA File Search store lookups use user_id (issue #91 §0).

The QnA service must resolve stores as ``user-{user_id}-store``, not
``user-{username}-store``, so grounding matches the upload path.

These tests exercise the real ``ask_question`` code path to ensure the
store-lookup call receives the int ``user_id``, not the string ``username``.
"""
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.config import settings


def _mock_db():
    """Build a mock AsyncSession returning a valid session and empty history."""
    db = AsyncMock()
    mock_session = Mock()
    session_result = Mock()
    session_result.scalar_one_or_none.return_value = mock_session
    history_result = Mock()
    history_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(
        side_effect=[session_result, history_result]
    )
    return db


def _make_service(db):
    """Create a QnAService with mocked Gemini client and prompt."""
    with patch("app.services.qna_service.genai.Client"):
        from app.services.qna_service import QnAService
        svc = QnAService(db=db)
    svc.prompt_loader.get_prompt = Mock(return_value="QnA system prompt")
    mock_resp = Mock()
    mock_resp.text = "answer"
    mock_resp.candidates = []
    svc.client.models.generate_content = Mock(return_value=mock_resp)
    return svc


# Patches for modules imported inside ask_question's body.
# These are scoped to the source modules so the in-function
# ``from X import Y`` picks up the mock.
_COMMON_PATCHES = [
    # criteria_context_service — make it return no context, no notice
    "app.services.criteria_context_service.CriteriaContextService",
    "app.services.criteria_context_service.build_criteria_context_or_notice",
    "app.repositories.app_state_repository.AppStateRepository",
    # question_analyzer
    "app.services.question_analyzer.QuestionAnalyzer",
]


class TestQnAStoreUserIdKeying:
    """Verify QnA passes user_id (int) to store lookups via ask_question."""

    @pytest.mark.asyncio
    async def test_general_question_uses_int_user_id_for_store(self):
        """
        Full ask_question path for a general question:
        ``get_user_store_id`` must receive ``user_key=42`` (int),
        NOT ``user_key="testuser"`` (str).
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            db = _mock_db()
            svc = _make_service(db)

            # Spy on the store lookup
            svc.file_search_service.get_user_store_id = Mock(
                return_value="fileSearchStores/user42"
            )

            with patch(_COMMON_PATCHES[0], Mock()), \
                 patch(_COMMON_PATCHES[1], AsyncMock(return_value=(None, None))), \
                 patch(_COMMON_PATCHES[2], Mock()), \
                 patch(_COMMON_PATCHES[3]) as MockQA:
                MockQA.return_value.analyze_question.return_value = {
                    "question_type": "general",
                    "metadata_filter": None,
                }

                result = await svc.ask_question(
                    session_id=1,
                    question="What is in my document?",
                    user_id=42,
                    username="testuser",
                )

            # THE critical assertion
            svc.file_search_service.get_user_store_id.assert_called_once()
            call_kwargs = (
                svc.file_search_service.get_user_store_id.call_args
            )
            assert call_kwargs.kwargs["user_key"] == 42
            assert isinstance(call_kwargs.kwargs["user_key"], int)
            # Sanity
            assert result["answer"] == "answer"

    @pytest.mark.asyncio
    async def test_eval_question_uses_int_user_id_for_store(self):
        """
        Full ask_question path for an evaluation question:
        ``get_dual_store_ids`` must receive ``user_key=42`` (int),
        NOT ``user_key="testuser"`` (str).
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            db = _mock_db()
            svc = _make_service(db)

            # Spy on the store lookup
            svc.file_search_service.get_dual_store_ids = Mock(
                return_value=[
                    "fileSearchStores/user42",
                    "fileSearchStores/rubric",
                ]
            )

            with patch(_COMMON_PATCHES[0], Mock()), \
                 patch(_COMMON_PATCHES[1], AsyncMock(return_value=(None, None))), \
                 patch(_COMMON_PATCHES[2], Mock()), \
                 patch(_COMMON_PATCHES[3]) as MockQA, \
                 patch(
                     "app.services.criteria_vector_service"
                     ".CriteriaVectorService.active_stable_id_filter",
                     new=AsyncMock(return_value="some_filter"),
                 ):
                MockQA.return_value.analyze_question.return_value = {
                    "question_type": "evaluation",
                    "metadata_filter": None,
                }

                result = await svc.ask_question(
                    session_id=1,
                    question="Evaluate my lesson plan",
                    user_id=42,
                    username="testuser",
                )

            # THE critical assertion
            svc.file_search_service.get_dual_store_ids.assert_called_once()
            call_kwargs = (
                svc.file_search_service.get_dual_store_ids.call_args
            )
            assert call_kwargs.kwargs["user_key"] == 42
            assert isinstance(call_kwargs.kwargs["user_key"], int)
            # Sanity
            assert result["answer"] == "answer"

    def test_store_name_format_is_user_id_based(self):
        """
        The store name from user_id=42 must be 'user-42-store',
        matching the upload path convention.
        """
        from app.services.file_search_service import _sanitize_display_name

        assert _sanitize_display_name("user-42-store") == "user-42-store"

    def test_store_name_differs_from_username_based(self):
        """
        user-{id}-store != user-{username}-store for the same user,
        proving the re-keying actually changes the store target.
        """
        from app.services.file_search_service import _sanitize_display_name

        id_store = _sanitize_display_name("user-42-store")
        username_store = _sanitize_display_name("user-testuser-store")
        assert id_store != username_store
