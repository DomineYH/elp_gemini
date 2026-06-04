"""
FileSearchService - get_dual_store_ids() 메서드 테스트
Phase 1에서 추가된 공통 유틸리티 메서드 검증
"""
import pytest
from unittest.mock import Mock, patch
from app.services.file_search_service import FileSearchService
from app.config import settings


class TestGetDualStoreIds:
    """
    get_dual_store_ids() 메서드 테스트 (Phase 1)
    rubricstore와 사용자 스토어 조회/생성 로직 검증
    """

    def test_get_dual_store_ids_success(self):
        """
        rubricstore + 사용자 스토어 조회 성공
        """
        with patch.object(settings, 'GOOGLE_API_KEY', 'test-key'):
            with patch('app.services.file_search_service.genai.Client'):
                service = FileSearchService()

                # Mock stores
                mock_rubric = Mock()
                mock_rubric.display_name = "rubricstore"
                mock_rubric.name = "fileSearchStores/rubric123"

                mock_user = Mock()
                mock_user.display_name = "user-123-store"
                mock_user.name = "fileSearchStores/user123"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_rubric, mock_user]
                )

                # When
                result = service.get_dual_store_ids(user_key=123)

                # Then
                assert len(result) == 2
                assert "fileSearchStores/rubric123" in result
                assert "fileSearchStores/user123" in result

    def test_get_dual_store_ids_no_rubricstore(self):
        """
        rubricstore 없을 시 ValueError 발생
        """
        with patch.object(settings, 'GOOGLE_API_KEY', 'test-key'):
            with patch('app.services.file_search_service.genai.Client'):
                service = FileSearchService()

                # rubricstore 없음
                mock_other = Mock()
                mock_other.display_name = "other-store"
                mock_other.name = "fileSearchStores/other"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_other]
                )

                # When & Then
                with pytest.raises(ValueError) as exc_info:
                    service.get_dual_store_ids(user_key=123)

                assert "rubricstore" in str(exc_info.value)

    def test_get_dual_store_ids_create_user_store(self):
        """
        사용자 스토어 없을 시 자동 생성
        """
        with patch.object(settings, 'GOOGLE_API_KEY', 'test-key'):
            with patch('app.services.file_search_service.genai.Client'):
                service = FileSearchService()

                # rubricstore만 있음
                mock_rubric = Mock()
                mock_rubric.display_name = "rubricstore"
                mock_rubric.name = "fileSearchStores/rubric"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_rubric]
                )

                # 사용자 스토어 생성 Mock
                mock_created = Mock()
                mock_created.name = "fileSearchStores/user999"
                service._get_or_create_store = Mock(
                    return_value=mock_created
                )

                # When
                result = service.get_dual_store_ids(user_key=999)

                # Then
                assert len(result) == 2
                service._get_or_create_store.assert_called_once_with(
                    "user-999-store"
                )

    def test_get_dual_store_ids_caching(self):
        """
        60초 이내 재호출 시 캐시 사용
        """
        with patch.object(settings, 'GOOGLE_API_KEY', 'test-key'):
            with patch('app.services.file_search_service.genai.Client'):
                service = FileSearchService()

                # Mock stores
                mock_rubric = Mock()
                mock_rubric.display_name = "rubricstore"
                mock_rubric.name = "fileSearchStores/rubric"

                mock_user = Mock()
                mock_user.display_name = "user-123-store"
                mock_user.name = "fileSearchStores/user123"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_rubric, mock_user]
                )

                # When
                result1 = service.get_dual_store_ids(user_key=123)
                result2 = service.get_dual_store_ids(user_key=123)

                # Then
                assert result1 == result2
                # list() 한 번만 호출 (캐시 히트)
                assert (
                    service.client.file_search_stores.list.call_count
                    == 1
                )

    @pytest.mark.asyncio
    async def test_delete_store_by_display_name_force_true(self):
        """
        delete_store_by_display_name() force=True 사용 확인
        """
        with patch.object(settings, 'GOOGLE_API_KEY', 'test-key'):
            with patch('app.services.file_search_service.genai.Client'):
                service = FileSearchService()

                # Mock store
                mock_store = Mock()
                mock_store.display_name = "test-store"
                mock_store.name = "fileSearchStores/test123"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_store]
                )
                service.client.file_search_stores.delete = Mock()

                # When
                await service.delete_store_by_display_name("test-store")

                # Then
                service.client.file_search_stores.delete \
                    .assert_called_once_with(
                        name=mock_store.name,
                        config={'force': True}
                    )
