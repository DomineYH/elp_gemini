"""
CriteriaEmbeddingService 재시도 관련 테스트
연결 오류 시 재시도 로직 검증
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)


@pytest.mark.asyncio
class TestCriteriaEmbeddingServiceRetry:
    """재시도 로직 테스트"""

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_retries_on_connection_error(
        self, mock_genai, mock_settings
    ):
        """연결 오류 시 재시도 후 성공"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        # Mock 새 스토어 생성 (각 재시도마다 새 스토어)
        mock_stores = [
            MagicMock(name=f"stores/retry-{i}")
            for i in range(3)
        ]

        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.side_effect = (
            mock_stores
        )

        # 처음 2번 실패, 3번째 성공
        mock_operation_success = MagicMock()
        mock_operation_success.done = True
        mock_operation_success.response.parent = (
            "stores/vector-success"
        )
        mock_operation_success.response.document_name = (
            "docs/test"
        )

        upload_mock = fss.upload_to_file_search_store
        upload_mock.side_effect = [
            ConnectionError("Network error 1"),
            ConnectionError("Network error 2"),
            mock_operation_success,
        ]

        # delete는 항상 성공
        fss.delete = MagicMock()

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act
        result = await service.upload_and_embed(
            file_path="test.pdf",
            title="test retry",
        )

        # Assert
        assert result == "stores/vector-success"
        assert upload_mock.call_count == 3
        # 처음 2번 실패 시 스토어 정리 확인
        assert (
            fss.delete.call_count
            == 2
        )

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_fails_after_max_retries(
        self, mock_genai, mock_settings
    ):
        """최대 재시도 후에도 실패"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        # Mock 스토어 생성 (3번 시도)
        mock_stores = [
            MagicMock(name=f"stores/fail-{i}")
            for i in range(3)
        ]

        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.side_effect = (
            mock_stores
        )

        # 계속 실패
        upload_mock = fss.upload_to_file_search_store
        upload_mock.side_effect = ConnectionError(
            "Persistent error"
        )

        # delete는 항상 성공
        fss.delete = MagicMock()

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act & Assert
        with pytest.raises(ConnectionError):
            await service.upload_and_embed(
                file_path="test.pdf",
                title="test fail",
            )

        # 3번 시도 확인
        assert upload_mock.call_count == 3
        # 3번 모두 실패 시 스토어 정리 확인
        assert (
            fss.delete.call_count
            == 3
        )
