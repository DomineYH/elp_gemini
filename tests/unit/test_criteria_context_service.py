"""
CriteriaContextService 단위 테스트
활성 기준 컨텍스트 검색 기능 검증
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.criteria_context_service import (
    CriteriaContextService,
)


@pytest.mark.asyncio
class TestCriteriaContextService:
    """CriteriaContextService 테스트"""

    @patch(
        "app.services.criteria_context_service.settings"
    )
    @patch(
        "app.services.criteria_context_service.genai"
    )
    def test_init_success(self, mock_genai, mock_settings):
        """정상 초기화 테스트"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-api-key"

        # Act
        service = CriteriaContextService()

        # Assert
        assert service.client is not None
        mock_genai.Client.assert_called_once_with(
            api_key="test-api-key"
        )

    @patch(
        "app.services.criteria_context_service.settings"
    )
    def test_init_no_api_key(self, mock_settings):
        """API Key 없을 때 초기화 실패"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = None

        # Act & Assert
        with pytest.raises(ValueError) as exc:
            CriteriaContextService()

        assert (
            "GOOGLE_API_KEY" in str(exc.value)
        )

    @patch(
        "app.services.criteria_context_service.types"
    )
    @patch(
        "app.services.criteria_context_service"
        ".criteria_context_provider"
    )
    @patch(
        "app.services.criteria_context_service.settings"
    )
    @patch(
        "app.services.criteria_context_service.genai"
    )
    async def test_get_context_success(
        self,
        mock_genai,
        mock_settings,
        mock_provider,
        mock_types,
    ):
        """정상 컨텍스트 검색 테스트"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.GEMINI_EVAL_MODEL = (
            "gemini-1.5-pro"
        )

        # Mock ContextProvider
        mock_provider.has_active_criteria.return_value = (
            True
        )
        mock_provider.get_active_vector_store_id.return_value = (
            "stores/vector-123"
        )
        mock_provider.get_active_criteria_id.return_value = (
            1
        )

        # Mock Types
        mock_types.FileSearchTool = MagicMock()
        mock_types.Tool = MagicMock()
        mock_types.GenerateContentConfig = MagicMock()

        # Mock Response
        mock_response = MagicMock()
        mock_response.text = (
            "평가 기준: 품질 우선"
        )

        # Mock Client
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = (
            mock_response
        )

        mock_genai.Client.return_value = mock_client

        service = CriteriaContextService()
        service.client = mock_client

        # Act
        results = await service.get_context(
            query="품질 평가 기준", k=5
        )

        # Assert
        assert len(results) > 0
        assert results[0]["content"] == (
            "평가 기준: 품질 우선"
        )
        assert results[0]["score"] == 1.0
        assert results[0]["metadata"]["source"] == (
            "criteria"
        )

    @patch(
        "app.services.criteria_context_service"
        ".criteria_context_provider"
    )
    @patch(
        "app.services.criteria_context_service.settings"
    )
    @patch(
        "app.services.criteria_context_service.genai"
    )
    async def test_get_context_no_active(
        self,
        mock_genai,
        mock_settings,
        mock_provider,
    ):
        """활성 기준 없을 때 예외 발생"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"

        # Mock ContextProvider (활성 기준 없음)
        mock_provider.has_active_criteria.return_value = (
            False
        )

        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        service = CriteriaContextService()
        service.client = mock_client

        # Act & Assert
        with pytest.raises(ValueError) as exc:
            await service.get_context(
                query="테스트 쿼리", k=5
            )

        assert (
            "활성화된 평가 기준이 없습니다"
            in str(exc.value)
        )

    @patch(
        "app.services.criteria_context_service.types"
    )
    @patch(
        "app.services.criteria_context_service"
        ".criteria_context_provider"
    )
    @patch(
        "app.services.criteria_context_service.settings"
    )
    @patch(
        "app.services.criteria_context_service.genai"
    )
    async def test_get_context_api_error(
        self,
        mock_genai,
        mock_settings,
        mock_provider,
        mock_types,
    ):
        """API 호출 실패 시 예외 전파"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.GEMINI_EVAL_MODEL = (
            "gemini-1.5-pro"
        )

        # Mock ContextProvider
        mock_provider.has_active_criteria.return_value = (
            True
        )
        mock_provider.get_active_vector_store_id.return_value = (
            "stores/vector-123"
        )
        mock_provider.get_active_criteria_id.return_value = (
            1
        )

        # Mock Types
        mock_types.FileSearchTool = MagicMock()
        mock_types.Tool = MagicMock()
        mock_types.GenerateContentConfig = MagicMock()

        # Mock Client (API 에러)
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = (
            Exception("API Error")
        )

        mock_genai.Client.return_value = mock_client

        service = CriteriaContextService()
        service.client = mock_client

        # Act & Assert
        with pytest.raises(Exception) as exc:
            await service.get_context(
                query="테스트 쿼리", k=5
            )

        assert "API Error" in str(exc.value)

    @patch(
        "app.services.criteria_context_service.types"
    )
    @patch(
        "app.services.criteria_context_service"
        ".criteria_context_provider"
    )
    @patch(
        "app.services.criteria_context_service.settings"
    )
    @patch(
        "app.services.criteria_context_service.genai"
    )
    async def test_get_context_with_k_limit(
        self,
        mock_genai,
        mock_settings,
        mock_provider,
        mock_types,
    ):
        """k 파라미터 제한 테스트"""
        # Arrange
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.GEMINI_EVAL_MODEL = (
            "gemini-1.5-pro"
        )

        # Mock ContextProvider
        mock_provider.has_active_criteria.return_value = (
            True
        )
        mock_provider.get_active_vector_store_id.return_value = (
            "stores/vector-123"
        )
        mock_provider.get_active_criteria_id.return_value = (
            1
        )

        # Mock Types
        mock_types.FileSearchTool = MagicMock()
        mock_types.Tool = MagicMock()
        mock_types.GenerateContentConfig = MagicMock()

        # Mock Response (여러 결과)
        mock_response = MagicMock()
        mock_response.text = (
            "기준 1, 기준 2, 기준 3, "
            "기준 4, 기준 5, 기준 6"
        )

        # Mock Client
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = (
            mock_response
        )

        mock_genai.Client.return_value = mock_client

        service = CriteriaContextService()
        service.client = mock_client

        # Act (k=3으로 제한)
        results = await service.get_context(
            query="모든 기준", k=3
        )

        # Assert
        assert len(results) <= 3
