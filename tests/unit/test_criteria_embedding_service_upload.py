"""
CriteriaEmbeddingService 업로드 관련 테스트
기본 업로드 기능 검증
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)


@pytest.mark.asyncio
class TestCriteriaEmbeddingServiceUpload:
    """기본 업로드 테스트"""

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_and_embed_success(
        self, mock_genai, mock_settings
    ):
        """정상 업로드 및 임베딩 (고유 스토어 생성)"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        # Mock 새 스토어 생성
        mock_new_store = MagicMock()
        mock_new_store.name = "stores/criteria-unique-123"

        # Mock Client
        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_new_store
        )

        # Mock Operation (완료 상태)
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.response.parent = (
            "stores/vector-unique-123"
        )
        mock_operation.response.document_name = (
            "docs/test-doc"
        )

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = (
            mock_operation
        )

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act
        result = await service.upload_and_embed(
            file_path="/test.pdf",
            title="Test Criteria",
            metadata={"version": "1.0"},
        )

        # Assert
        # Phase 2: 반환 타입이 Tuple[str, str]로 변경됨
        assert isinstance(result, tuple)
        assert len(result) == 2
        vector_store_id, document_id = result
        assert vector_store_id == "stores/vector-unique-123"
        assert document_id == "docs/test-doc"
        # 매번 새 스토어 생성 확인
        fss.create.assert_called_once()
        upload_mock.assert_called_once()

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_upload_and_embed_timeout(
        self, mock_genai, mock_settings
    ):
        """업로드 타임아웃 (고유 스토어 생성)"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 1
        mock_settings.FS_POLL_INTERVAL = 0.5

        # Mock 새 스토어 생성
        mock_new_store = MagicMock()
        mock_new_store.name = "stores/criteria-timeout-123"

        # Mock Client
        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.return_value = (
            mock_new_store
        )

        # Mock Operation (완료되지 않음)
        mock_operation = MagicMock()
        mock_operation.done = False

        upload_mock = fss.upload_to_file_search_store
        upload_mock.return_value = (
            mock_operation
        )
        mock_client.operations.get.return_value = (
            mock_operation
        )

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act & Assert
        with pytest.raises(TimeoutError) as exc:
            await service.upload_and_embed(
                file_path="/test.pdf",
                title="Test Criteria",
            )

        assert "타임아웃" in str(exc.value)

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    async def test_multiple_uploads_different_store_ids(
        self, mock_genai, mock_settings
    ):
        """
        연속 업로드 시 각각 다른 vector_store_id 확인
        """
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.FS_CHUNKING_MAX_TOKENS = 1000
        mock_settings.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock_settings.FS_UPLOAD_TIMEOUT = 60
        mock_settings.FS_POLL_INTERVAL = 1

        mock_client = MagicMock()

        # 첫 번째 업로드
        mock_store_1 = MagicMock()
        mock_store_1.name = "stores/criteria-1000-aaa1"
        mock_operation_1 = MagicMock()
        mock_operation_1.done = True
        mock_operation_1.response.parent = (
            "stores/vector-id-111"
        )
        mock_operation_1.response.document_name = "docs/doc-1"

        # 두 번째 업로드
        mock_store_2 = MagicMock()
        mock_store_2.name = "stores/criteria-2000-bbb2"
        mock_operation_2 = MagicMock()
        mock_operation_2.done = True
        mock_operation_2.response.parent = (
            "stores/vector-id-222"
        )
        mock_operation_2.response.document_name = "docs/doc-2"

        fss = mock_client.file_search_stores
        fss.create.side_effect = [
            mock_store_1,
            mock_store_2,
        ]

        upload_mock = fss.upload_to_file_search_store
        upload_mock.side_effect = [
            mock_operation_1,
            mock_operation_2,
        ]

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act
        result_1 = await service.upload_and_embed(
            file_path="/doc1.pdf",
            title="Document A",
        )
        result_2 = await service.upload_and_embed(
            file_path="/doc2.pdf",
            title="Document B",
        )

        # Assert
        # Phase 2: 반환 타입이 Tuple[str, str]로 변경됨
        assert isinstance(result_1, tuple)
        assert isinstance(result_2, tuple)
        vector_id_1, doc_id_1 = result_1
        vector_id_2, doc_id_2 = result_2

        assert vector_id_1 == "stores/vector-id-111"
        assert vector_id_2 == "stores/vector-id-222"
        assert vector_id_1 != vector_id_2

        assert doc_id_1 == "docs/doc-1"
        assert doc_id_2 == "docs/doc-2"
        assert doc_id_1 != doc_id_2
        # 각 업로드마다 새 스토어 생성 확인
        assert fss.create.call_count == 2
