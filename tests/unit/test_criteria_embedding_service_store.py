"""
CriteriaEmbeddingService 스토어 관련 테스트
Vector Store 생성 및 삭제 검증
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)


@pytest.mark.asyncio
class TestCriteriaEmbeddingServiceStore:
    """스토어 생성 및 삭제 테스트"""

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    def test_init_success(self, mock_genai, mock_settings):
        """정상 초기화 테스트"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-api-key"

        # Act
        service = CriteriaEmbeddingService()

        # Assert
        assert service.client is not None
        mock_genai.Client.assert_called_once_with(
            api_key="test-api-key"
        )

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    def test_init_no_api_key(self, mock_settings):
        """API Key 없을 때 초기화 실패"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = None

        # Act & Assert
        with pytest.raises(ValueError) as exc:
            CriteriaEmbeddingService()

        assert (
            "GOOGLE_API_KEY" in str(exc.value)
        )

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    def test_create_unique_store_generates_unique_names(
        self, mock_genai, mock_settings
    ):
        """
        _create_unique_store가 매번 고유한 이름 생성 검증
        """
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_client = MagicMock()

        # 첫 번째 스토어
        mock_store_1 = MagicMock()
        mock_store_1.name = "stores/criteria-1234-abc1"
        # 두 번째 스토어
        mock_store_2 = MagicMock()
        mock_store_2.name = "stores/criteria-1235-abc2"

        fss = mock_client.file_search_stores
        fss.create.side_effect = [
            mock_store_1,
            mock_store_2,
        ]

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act
        store_1 = service._create_unique_store("Doc A")
        store_2 = service._create_unique_store("Doc B")

        # Assert
        assert store_1.name != store_2.name
        assert fss.create.call_count == 2
        # 스토어 이름 형식 검증
        assert "criteria-" in store_1.name
        assert "criteria-" in store_2.name

    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    def test_create_unique_store_failure(
        self, mock_genai, mock_settings
    ):
        """스토어 생성 실패 시 예외 발생 확인"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_client = MagicMock()
        fss = mock_client.file_search_stores
        fss.create.side_effect = (
            Exception("API Error: Rate limit exceeded")
        )

        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act & Assert
        with pytest.raises(Exception) as exc:
            service._create_unique_store("Failed Doc")

        assert "API Error" in str(exc.value)

    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    async def test_delete_store_success(
        self, mock_settings, mock_genai
    ):
        """스토어 삭제 성공"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"

        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act
        result = await service.delete_store(
            "stores/test-store-123"
        )

        # Assert
        assert result is True
        fss = mock_client.file_search_stores
        fss.delete.assert_called_once()

    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    async def test_delete_store_failure_ignored(
        self, mock_settings, mock_genai
    ):
        """삭제 실패하지만 예외 삼킴 (ignore_errors=True)"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"

        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # 삭제 실패 시뮬레이션
        fss = mock_client.file_search_stores
        fss.delete.side_effect = (
            Exception("Not found")
        )

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act
        result = await service.delete_store(
            "stores/nonexistent",
            ignore_errors=True
        )

        # Assert
        assert result is False

    @patch(
        "app.services.criteria_embedding_service.genai"
    )
    @patch(
        "app.services.criteria_embedding_service.settings"
    )
    async def test_delete_store_failure_raises(
        self, mock_settings, mock_genai
    ):
        """삭제 실패 시 예외 재발생 (ignore_errors=False)"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"

        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # 삭제 실패 시뮬레이션
        fss = mock_client.file_search_stores
        fss.delete.side_effect = (
            Exception("Not found")
        )

        service = CriteriaEmbeddingService()
        service.client = mock_client

        # Act & Assert
        with pytest.raises(Exception, match="Not found"):
            await service.delete_store(
                "stores/nonexistent",
                ignore_errors=False
            )
