"""
CriteriaEmbeddingService 메타데이터 관련 테스트
메타데이터 포함 업로드 검증
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)


@pytest.mark.asyncio
class TestCriteriaEmbeddingServiceMetadata:
    """메타데이터 관련 테스트"""

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_and_embed_with_metadata(
        self, mock_genai, mock_settings
    ):
        """메타데이터 포함 업로드 (고유 스토어 생성)"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        # Mock 새 스토어
        mock_new_store = MagicMock()
        mock_new_store.name = "stores/criteria-meta-123"

        # Mock Client
        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_new_store
        )

        # Mock Operation
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.response.parent = (
            "stores/vector-meta-789"
        )
        mock_operation.response.document_name = (
            "docs/meta-doc"
        )

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = mock_operation

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act
        metadata = {
            "version": "2.0",
            "category": "quality",
            "priority": 1,
        }
        vector_store_id = (
            await service.upload_and_embed(
                file_path="/meta.pdf",
                title="Criteria with Metadata",
                metadata=metadata,
            )
        )

        # Assert
        assert vector_store_id == "stores/vector-meta-789"
        fss.create.assert_called_once()
        upload_mock.assert_called_once()

        # 메타데이터 구조 검증
        call_args = upload_mock.call_args[1]
        custom_metadata = call_args["config"][
            "custom_metadata"
        ]

        # numeric_value와 string_value 확인
        assert len(custom_metadata) == 3

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
