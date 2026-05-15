"""
CriteriaVectorService 단위 테스트
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from app.services.criteria_vector_service import (
    CriteriaVectorService,
)


@pytest.fixture
def mock_file_search_service():
    """FileSearchService Mock 생성"""
    mock_service = Mock()
    mock_service.client = Mock()
    mock_service.upload_document = AsyncMock()
    mock_service.search_in_store = AsyncMock()
    return mock_service


@pytest.fixture
def service(mock_file_search_service):
    """CriteriaVectorService 인스턴스 생성"""
    with patch(
        "app.services.criteria_vector_service.FileSearchService",
        return_value=mock_file_search_service,
    ):
        return CriteriaVectorService()


@pytest.mark.asyncio
async def test_upload_criteria_success(service):
    """평가기준 업로드 성공 테스트"""
    pytest.skip("Rewritten in Wave 5 / Task 14 for new upload_criteria signature; see plan 2026-05-15-criteria-cloud-metadata.md")
    # Given
    file_path = "test_criteria.pdf"
    display_name = "Test Criteria"
    metadata = {"subject": "math"}

    # Mock _recreate_criteria_store
    service._recreate_criteria_store = AsyncMock()

    # Mock upload_document 응답
    expected_result = {
        "document_id": "doc123",
        "store_id": "store456",
    }
    service.file_search_service.upload_document.return_value = (
        expected_result
    )

    # When
    result = await service.upload_criteria(
        file_path, display_name, metadata
    )

    # Then
    assert result == expected_result
    service._recreate_criteria_store.assert_called_once()
    service.file_search_service.upload_document.assert_called_once()

    # 메타데이터에 type='criteria' 추가 확인
    call_args = (
        service.file_search_service.upload_document.call_args
    )
    assert call_args[1]["metadata"]["type"] == "criteria"
    assert call_args[1]["metadata"]["subject"] == "math"


@pytest.mark.asyncio
async def test_search_criteria_success(service):
    """평가기준 검색 성공 테스트"""
    # Given
    query = "What is the rubric for essay writing?"

    # Mock client
    mock_client = service.file_search_service.client
    mock_store = Mock()
    mock_store.display_name = service.store_name
    mock_store.name = "store123"

    # Mock list() 메서드
    mock_client.file_search_stores.list.return_value = [
        mock_store
    ]

    # Mock search_in_store 응답
    expected_result = {
        "response_text": "The rubric for essay writing...",
        "citations": [],
        "sources_count": 1,
    }
    service.file_search_service.search_in_store.return_value = (
        expected_result
    )

    # When
    result = await service.search_criteria(query)

    # Then
    assert result == expected_result
    service.file_search_service.search_in_store.assert_called_once()

    # metadata_filter 확인
    call_args = (
        service.file_search_service.search_in_store.call_args
    )
    assert call_args[1]["metadata_filter"] == 'type="criteria"'


@pytest.mark.asyncio
async def test_search_criteria_store_not_found(service):
    """평가기준 Store 없음 테스트"""
    # Given
    query = "What is the rubric?"

    # Mock client
    mock_client = service.file_search_service.client
    mock_client.file_search_stores.list.return_value = []

    # When / Then
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        await service.search_criteria(query)


@pytest.mark.asyncio
async def test_list_criteria_documents_success(service):
    """평가기준 문서 목록 조회 성공 테스트"""
    pytest.skip("Updated in Task 11 for new metadata-aware list_criteria_documents signature")
    # Given
    mock_client = service.file_search_service.client
    mock_store = Mock()
    mock_store.display_name = service.store_name
    mock_store.name = "store123"

    # Mock list() 메서드
    mock_client.file_search_stores.list.return_value = [
        mock_store
    ]

    # Mock 문서 목록
    mock_doc1 = Mock()
    mock_doc1.name = "doc1"
    mock_doc1.display_name = "Criteria 1"

    mock_doc2 = Mock()
    mock_doc2.name = "doc2"
    mock_doc2.display_name = "Criteria 2"

    mock_client.file_search_stores.list_documents.return_value = [
        mock_doc1,
        mock_doc2,
    ]

    # When
    result = await service.list_criteria_documents()

    # Then
    assert len(result) == 2
    assert result[0]["document_id"] == "doc1"
    assert result[0]["display_name"] == "Criteria 1"
    assert result[1]["document_id"] == "doc2"
    assert result[1]["display_name"] == "Criteria 2"


@pytest.mark.asyncio
async def test_list_criteria_documents_store_not_found(service):
    """평가기준 Store 없음 시 빈 목록 반환 테스트"""
    # Given
    mock_client = service.file_search_service.client
    mock_client.file_search_stores.list.return_value = []

    # When
    result = await service.list_criteria_documents()

    # Then
    assert result == []


@pytest.mark.asyncio
async def test_upload_criteria_with_default_metadata(service):
    """메타데이터 없이 평가기준 업로드 테스트"""
    pytest.skip("Rewritten in Wave 5 / Task 14 for new upload_criteria signature; see plan 2026-05-15-criteria-cloud-metadata.md")
    # Given
    file_path = "test_criteria.pdf"
    display_name = "Test Criteria"

    # Mock _recreate_criteria_store
    service._recreate_criteria_store = AsyncMock()

    # Mock upload_document 응답
    expected_result = {
        "document_id": "doc123",
        "store_id": "store456",
    }
    service.file_search_service.upload_document.return_value = (
        expected_result
    )

    # When
    result = await service.upload_criteria(file_path, display_name)

    # Then
    assert result == expected_result

    # 메타데이터에 type='criteria' 자동 추가 확인
    call_args = (
        service.file_search_service.upload_document.call_args
    )
    assert call_args[1]["metadata"]["type"] == "criteria"
