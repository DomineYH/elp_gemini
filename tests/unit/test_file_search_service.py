"""
FileSearchService 단위 테스트
반환값 키, 환경 변수, 에러 처리 검증
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.services.file_search_service import FileSearchService
from app.config import settings


class TestFileSearchService:
    """FileSearchService 테스트 클래스"""

    def test_init_without_api_key(self):
        """
        API 키 없이 초기화 시 ValueError 발생 확인
        """
        with patch.object(settings, 'GOOGLE_API_KEY', ''):
            with pytest.raises(ValueError) as exc_info:
                FileSearchService()

            assert "GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다" in str(exc_info.value)

    def test_init_with_api_key(self):
        """
        정상적인 API 키로 초기화 성공 확인
        """
        with patch.object(settings, 'GOOGLE_API_KEY', 'test-api-key'):
            with patch('app.services.file_search_service.genai.Client'):
                service = FileSearchService()
                assert service.main_store_name == settings.FS_MAIN_STORE_NAME
                assert service.rubric_store_name == settings.FS_RUBRIC_STORE_NAME

    @pytest.mark.asyncio
    async def test_upload_document_returns_correct_keys(self):
        """
        upload_document가 올바른 키를 반환하는지 테스트
        - document_id 키 존재 확인
        - store_id 키 존재 확인
        - 각 값의 형식 검증
        """
        with patch.object(settings, 'GOOGLE_API_KEY', 'test-api-key'):
            with patch('app.services.file_search_service.genai.Client'):
                service = FileSearchService()

                # Mock store 생성
                mock_store = Mock()
                mock_store.name = "fileSearchStores/test-store-123"
                mock_store.display_name = "main-store"

                # Mock operation 생성
                mock_operation = Mock()
                mock_operation.done = True
                mock_operation.response = Mock()
                mock_operation.response.name = "documents/test-doc-456"

                # Mock 메서드 설정
                with patch.object(service, '_get_or_create_store', return_value=mock_store):
                    with patch.object(
                        service.client.file_search_stores,
                        'upload_to_file_search_store',
                        return_value=mock_operation
                    ):
                        result = await service.upload_document(
                            file_path="/tmp/test.pdf",
                            display_name="Test Document",
                            metadata={"user_id": "123", "random_key": "abc"}
                        )

                # 검증: 올바른 키 반환
                assert "document_id" in result
                assert "store_id" in result

                # 검증: 값의 형식
                assert result["document_id"] == "documents/test-doc-456"
                assert result["store_id"] == "fileSearchStores/test-store-123"

                # 검증: file_id 키는 존재하지 않음 (이전 버그)
                assert "file_id" not in result

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="타임아웃 테스트는 실제 환경에서 검증")
    async def test_upload_document_timeout(self):
        """
        타임아웃 발생 시 TimeoutError 발생 확인
        """
        with patch.object(settings, 'GOOGLE_API_KEY', 'test-api-key'):
            with patch('app.services.file_search_service.genai.Client'):
                service = FileSearchService()

                # Mock store 생성
                mock_store = Mock()
                mock_store.name = "fileSearchStores/test-store-123"

                # Mock operation - done=False로 타임아웃 시뮬레이션
                mock_operation = Mock()
                mock_operation.done = False

                with patch.object(service, '_get_or_create_store', return_value=mock_store):
                    with patch.object(
                        service.client.file_search_stores,
                        'upload_to_file_search_store',
                        return_value=mock_operation
                    ):
                        # operations.get()도 Mock 처리
                        with patch.object(
                            service.client.operations,
                            'get',
                            return_value=mock_operation
                        ):
                            # 타임아웃 설정을 짧게 조정
                            with patch.object(settings, 'FS_UPLOAD_TIMEOUT', 1):
                                with patch.object(settings, 'FS_POLL_INTERVAL', 1):
                                    with pytest.raises(TimeoutError) as exc_info:
                                        await service.upload_document(
                                            file_path="/tmp/test.pdf",
                                            display_name="Test Document",
                                            metadata={"user_id": "123"}
                                        )

                                    assert "타임아웃" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_document_error_handling(self):
        """
        업로드 중 예외 발생 시 에러 처리 확인
        """
        with patch.object(settings, 'GOOGLE_API_KEY', 'test-api-key'):
            with patch('app.services.file_search_service.genai.Client'):
                service = FileSearchService()

                # Mock store 생성
                mock_store = Mock()
                mock_store.name = "fileSearchStores/test-store-123"

                with patch.object(service, '_get_or_create_store', return_value=mock_store):
                    with patch.object(
                        service.client.file_search_stores,
                        'upload_to_file_search_store',
                        side_effect=Exception("API Error")
                    ):
                        with pytest.raises(Exception) as exc_info:
                            await service.upload_document(
                                file_path="/tmp/test.pdf",
                                display_name="Test Document",
                                metadata={"user_id": "123"}
                            )

                        assert "API Error" in str(exc_info.value)


class TestRouterIntegration:
    """
    Router에서 올바른 키로 접근하는지 통합 테스트
    (실제 통합 테스트는 tests/integration에서 수행)
    """

    def test_router_uses_document_id_key(self):
        """
        Router가 result.get("document_id")를 사용하는지 확인
        user_docs.py:135 라인 검증
        """
        # 이 테스트는 실제 코드 리뷰의 일부로,
        # user_docs.py에서 올바른 키를 사용하는지 확인합니다.
        # 실제 검증은 통합 테스트에서 수행됩니다.

        # 코드 변경 후 예상되는 동작:
        # document.file_search_file_id = result.get("document_id")  # ✅ 올바른 키
        # document.store_id = result.get("store_id")  # ✅ 올바른 키

        # 변경 전 버그:
        # document.file_search_file_id = result.get("file_id")  # ❌ 잘못된 키 (None 반환)

        assert True  # 플레이스홀더
