"""
CriteriaEmbeddingService 정리 관련 테스트
업로드 실패 시 스토어 자동 정리 검증
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)


@pytest.mark.asyncio
class TestCriteriaEmbeddingServiceCleanup:
    """업로드 실패 시 스토어 정리 테스트"""

    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    async def test_upload_failure_cleans_up_store(
        self, mock_settings, mock_genai
    ):
        """업로드 실패 시 스토어 정리 확인"""
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
        mock_store.name = "stores/test-store-cleanup"
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_store
        )

        # 업로드 실패 시뮬레이션
        upload_mock = fss.upload_to_file_search_store
        upload_mock.side_effect = Exception("Upload failed")

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act & Assert
        with pytest.raises(Exception, match="Upload failed"):
            await service.upload_and_embed(
                file_path="/test.pdf",
                title="test"
            )

        # 스토어 삭제가 호출되었는지 확인
        fss.delete.assert_called_once()
        call_args = (
            fss
            .delete
            .call_args
        )
        assert call_args.kwargs["name"] == (
            "stores/test-store-cleanup"
        )

    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    async def test_polling_timeout_cleans_up_store(
        self, mock_settings, mock_genai
    ):
        """폴링 타임아웃 시 스토어 정리 확인"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_UPLOAD_TIMEOUT = 2
        mock_settings.FS_POLL_INTERVAL = 1
        mock_settings.FS_CHUNKING_MAX_TOKENS = 512
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 128

        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # Mock Store
        mock_store = MagicMock()
        mock_store.name = "stores/test-store-timeout"
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_store
        )

        # 타임아웃 시뮬레이션 (영원히 미완료)
        mock_operation = MagicMock()
        mock_operation.name = "operations/test-timeout"
        mock_operation.done = False

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = mock_operation

        # operations.get()도 미완료 반환
        mock_client.operations.get.return_value = (
            mock_operation
        )

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act & Assert
        with pytest.raises(TimeoutError):
            await service.upload_and_embed(
                file_path="/test.pdf",
                title="test timeout"
            )

        # 스토어 삭제 확인
        fss.delete.assert_called_once()
        call_args = (
            fss
            .delete
            .call_args
        )
        assert call_args.kwargs["name"] == (
            "stores/test-store-timeout"
        )
