"""
CriteriaEmbeddingService Edge Case 테스트
빈 파일, 긴 제목, 특수 문자 등 경계 조건 검증
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)


@pytest.mark.asyncio
class TestCriteriaEmbeddingServiceEdgeCases:
    """Edge Case 테스트"""

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_empty_file(
        self, mock_genai, mock_settings
    ):
        """빈 파일 업로드 처리"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        mock_store = MagicMock()
        mock_store.name = "stores/empty-123"

        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_store
        )

        # 완료된 operation
        complete_op = MagicMock()
        complete_op.done = True
        complete_op.response.parent = (
            "stores/vector-empty-123"
        )

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = complete_op

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act - 빈 파일 (0 바이트)
        result = await service.upload_and_embed(
            file_path="",
            title="Empty File",
        )

        # Assert
        assert result == "stores/vector-empty-123"
        upload_mock.assert_called_once()

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_very_long_title(
        self, mock_genai, mock_settings
    ):
        """매우 긴 제목 (1000자) 처리"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        mock_store = MagicMock()
        mock_store.name = "stores/long-title-123"

        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_store
        )

        # 완료된 operation
        complete_op = MagicMock()
        complete_op.done = True
        complete_op.response.parent = (
            "stores/vector-long-123"
        )

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = complete_op

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act - 1000자 제목
        very_long_title = "A" * 1000
        result = await service.upload_and_embed(
            file_path="test.pdf",
            title=very_long_title,
        )

        # Assert
        assert result == "stores/vector-long-123"
        upload_mock.assert_called_once()

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_special_characters_in_title(
        self, mock_genai, mock_settings
    ):
        """특수 문자 포함 제목 처리"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        mock_store = MagicMock()
        mock_store.name = "stores/special-chars-123"

        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_store
        )

        # 완료된 operation
        complete_op = MagicMock()
        complete_op.done = True
        complete_op.response.parent = (
            "stores/vector-special-123"
        )

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = complete_op

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act - 특수 문자: 한글, 이모지, 기호
        special_title = (
            "테스트 📄 문서!@#$%^&*()_+-=[]{}|;':\",./<>?"
        )
        result = await service.upload_and_embed(
            file_path="test.pdf",
            title=special_title,
        )

        # Assert
        assert result == "stores/vector-special-123"
        upload_mock.assert_called_once()

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_with_metadata_dict(
        self, mock_genai, mock_settings
    ):
        """메타데이터 Dict 포함 업로드 처리"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        mock_store = MagicMock()
        mock_store.name = "stores/metadata-123"

        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_store
        )

        # 완료된 operation
        complete_op = MagicMock()
        complete_op.done = True
        complete_op.response.parent = (
            "stores/vector-metadata-123"
        )

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = complete_op

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act - 복잡한 메타데이터
        complex_metadata = {
            "department": "engineering",
            "priority": 1,
            "version": "2.5.3",
        }
        result = await service.upload_and_embed(
            file_path="test.pdf",
            title="Metadata Test",
            metadata=complex_metadata,
        )

        # Assert
        assert result == "stores/vector-metadata-123"
        upload_mock.assert_called_once()

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_with_unicode_title(
        self, mock_genai, mock_settings
    ):
        """유니코드 제목 (다양한 언어) 처리"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        mock_store = MagicMock()
        mock_store.name = "stores/unicode-123"

        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_store
        )

        # 완료된 operation
        complete_op = MagicMock()
        complete_op.done = True
        complete_op.response.parent = (
            "stores/vector-unicode-123"
        )

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = complete_op

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act - 다양한 언어
        unicode_title = "테스트 テスト 测试 тест"
        result = await service.upload_and_embed(
            file_path="test.pdf",
            title=unicode_title,
        )

        # Assert
        assert result == "stores/vector-unicode-123"
        upload_mock.assert_called_once()
