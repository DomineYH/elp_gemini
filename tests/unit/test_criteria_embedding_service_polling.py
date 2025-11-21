"""
CriteriaEmbeddingService 폴링 관련 테스트
LRO 폴링 및 operation.name 사용 검증
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)


@pytest.mark.asyncio
class TestCriteriaEmbeddingServicePolling:
    """폴링 및 operation.name 사용 테스트"""

    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    async def test_operations_get_uses_operation_name(
        self, mock_settings, mock_genai
    ):
        """operations.get()이 operation.name 사용 검증"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1
        mock_settings.FS_CHUNKING_MAX_TOKENS = 512
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 128

        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # Mock Store
        mock_store = MagicMock()
        mock_store.name = "stores/test-store-123"
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_store
        )

        # Mock Operation (초기: 미완료)
        mock_operation = MagicMock()
        mock_operation.name = "operations/test-op-123"
        mock_operation.done = False

        # Mock Operation (완료 상태)
        mock_complete_op = MagicMock()
        mock_complete_op.name = "operations/test-op-123"
        mock_complete_op.done = True
        mock_complete_op.response.parent = (
            "stores/test-store-123"
        )
        mock_complete_op.response.document_name = "docs/test"

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = mock_operation

        # operations.get()이 완료 상태 반환
        mock_client.operations.get.return_value = (
            mock_complete_op
        )

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act
        result = await service.upload_and_embed(
            file_path="/test.pdf",
            title="test"
        )

        # Assert
        # operations.get()이 operation.name 문자열 호출
        mock_client.operations.get.assert_called_with(
            "operations/test-op-123"  # ✅ name 전달
        )
        assert result == "stores/test-store-123"
