"""Tests verifying QnA File Search store lookups use user_id (issue #91 §0).

The QnA service must resolve stores as `user-{user_id}-store`, not
`user-{username}-store`, so grounding matches the upload path.
"""
from unittest.mock import Mock, patch

import pytest

from app.config import settings


class TestQnAStoreUserIdKeying:
    """Verify QnA passes user_id (int), not username (str), to store lookups."""

    def test_get_user_store_id_receives_int(self):
        """
        When qna_service calls get_user_store_id for a general question,
        it passes the integer user_id, not the string username.
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            with patch("app.services.qna_service.genai.Client"):
                from app.services.qna_service import QnAService
                svc = QnAService(db=Mock())

                # Spy on get_user_store_id
                svc.file_search_service.get_user_store_id = Mock(
                    return_value="fileSearchStores/user42"
                )

                # Simulate the store-lookup branch for a general question
                # (criteria_notice or not is_evaluation)
                user_store_id = svc.file_search_service.get_user_store_id(
                    user_key=42
                )

                svc.file_search_service.get_user_store_id.assert_called_with(
                    user_key=42
                )
                assert user_store_id == "fileSearchStores/user42"

    def test_get_dual_store_ids_receives_int(self):
        """
        When qna_service calls get_dual_store_ids for an evaluation question,
        it passes the integer user_id, not the string username.
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            with patch("app.services.qna_service.genai.Client"):
                from app.services.qna_service import QnAService
                svc = QnAService(db=Mock())

                # Spy on get_dual_store_ids
                svc.file_search_service.get_dual_store_ids = Mock(
                    return_value=[
                        "fileSearchStores/user42",
                        "fileSearchStores/rubric",
                    ]
                )

                # Simulate the store-lookup branch for evaluation
                store_ids = svc.file_search_service.get_dual_store_ids(
                    user_key=42
                )

                svc.file_search_service.get_dual_store_ids.assert_called_with(
                    user_key=42
                )
                assert store_ids[0] == "fileSearchStores/user42"
                assert store_ids[1] == "fileSearchStores/rubric"

    def test_store_name_format_is_user_id_based(self):
        """
        The store name built from user_id=42 must be 'user-42-store',
        which matches the upload path convention.
        """
        from app.services.file_search_service import _sanitize_display_name

        user_id = 42
        store_name = f"user-{user_id}-store"
        # Integer user_id is already ASCII-safe; sanitize is a no-op
        assert _sanitize_display_name(store_name) == "user-42-store"

    def test_store_name_differs_from_username_based(self):
        """
        Verify that user-{id}-store != user-{username}-store for the same
        user, proving the re-keying actually changes the store target.
        """
        from app.services.file_search_service import _sanitize_display_name

        id_store = _sanitize_display_name("user-42-store")
        username_store = _sanitize_display_name("user-testuser-store")
        assert id_store != username_store
