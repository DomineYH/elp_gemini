"""
LessonPlanVectorService 단위 테스트
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from app.services.lessonplan_vector_service import (
    LessonPlanVectorService
)


@pytest.fixture
def service():
    """LessonPlanVectorService 인스턴스 생성"""
    return LessonPlanVectorService()


@pytest.fixture
def mock_file_search_service():
    """FileSearchService Mock"""
    mock_service = Mock()
    mock_service.upload_document = AsyncMock(
        return_value={
            "document_id": "fileSearchStores/store1/documents/doc1",
            "store_id": "fileSearchStores/store1",
        }
    )
    mock_service.client = Mock()
    return mock_service


@pytest.mark.asyncio
async def test_upload_temporary_success(
    service, mock_file_search_service
):
    """임시 지도안 업로드 성공 테스트"""
    service.file_search_service = mock_file_search_service

    result = await service.upload_temporary(
        file_path="/tmp/test.pdf",
        display_name="테스트 지도안",
        user_id="user123",
        session_id="session456",
    )

    assert result["document_id"] == (
        "fileSearchStores/store1/documents/doc1"
    )
    assert result["store_id"] == "fileSearchStores/store1"

    # upload_document 호출 확인
    mock_file_search_service.upload_document.assert_called_once()
    call_args = (
        mock_file_search_service.upload_document.call_args
    )
    assert call_args[1]["file_path"] == "/tmp/test.pdf"
    assert call_args[1]["display_name"] == "테스트 지도안"
    assert call_args[1]["metadata"]["type"] == "lessonplan"
    assert call_args[1]["metadata"]["user_id"] == "user123"
    assert call_args[1]["metadata"]["session_id"] == "session456"


@pytest.mark.asyncio
async def test_upload_temporary_without_session(
    service, mock_file_search_service
):
    """세션 ID 없이 임시 지도안 업로드 테스트"""
    service.file_search_service = mock_file_search_service

    result = await service.upload_temporary(
        file_path="/tmp/test.pdf",
        display_name="테스트 지도안",
        user_id="user123",
    )

    assert result["document_id"]
    call_args = (
        mock_file_search_service.upload_document.call_args
    )
    assert "session_id" not in call_args[1]["metadata"]


@pytest.mark.asyncio
async def test_delete_on_logout_success(
    service, mock_file_search_service
):
    """로그아웃 시 지도안 삭제 테스트"""
    service.file_search_service = mock_file_search_service

    # Mock Store 리스트
    mock_store = Mock()
    mock_store.display_name = "user-user123-store"
    mock_store.name = "fileSearchStores/store1"

    mock_file_search_service.client.file_search_stores.list = (
        Mock(return_value=[mock_store])
    )
    mock_file_search_service.client.file_search_stores.delete = (
        Mock()
    )

    result = await service.delete_on_logout("user123")

    assert result is True
    (
        mock_file_search_service.client
        .file_search_stores.delete.assert_called_once_with(
            name="fileSearchStores/store1"
        )
    )


@pytest.mark.asyncio
async def test_delete_on_logout_store_not_found(
    service, mock_file_search_service
):
    """로그아웃 시 Store가 없는 경우 테스트"""
    service.file_search_service = mock_file_search_service

    # 빈 Store 리스트
    mock_file_search_service.client.file_search_stores.list = (
        Mock(return_value=[])
    )

    result = await service.delete_on_logout("user123")

    # Store가 없어도 성공 (warning만 출력)
    assert result is True


@pytest.mark.asyncio
async def test_delete_on_session_close(
    service, mock_file_search_service
):
    """세션 종료 시 지도안 삭제 테스트 (현재 미지원)"""
    service.file_search_service = mock_file_search_service

    result = await service.delete_on_session_close("session123")

    # 현재 API 제약으로 항상 True 반환
    assert result is True


@pytest.mark.asyncio
async def test_delete_user_documents_success(
    service, mock_file_search_service
):
    """사용자 문서 삭제 테스트"""
    service.file_search_service = mock_file_search_service

    # Mock Store 리스트
    mock_store = Mock()
    mock_store.display_name = "user-user123-store"
    mock_store.name = "fileSearchStores/store1"

    mock_file_search_service.client.file_search_stores.list = (
        Mock(return_value=[mock_store])
    )
    mock_file_search_service.client.file_search_stores.delete = (
        Mock()
    )

    result = await service.delete_user_documents("user123")

    assert result is True


@pytest.mark.asyncio
async def test_cleanup_expired_sessions(
    service, mock_file_search_service
):
    """만료 세션 정리 테스트"""
    service.file_search_service = mock_file_search_service

    # Mock Store 리스트 (빈 Store)
    mock_store1 = Mock()
    mock_store1.display_name = "user-user123-store"
    mock_store1.name = "fileSearchStores/store1"

    mock_store2 = Mock()
    mock_store2.display_name = "user-user456-store"
    mock_store2.name = "fileSearchStores/store2"

    # 메인 Store (무시되어야 함)
    mock_store3 = Mock()
    mock_store3.display_name = "main-store"
    mock_store3.name = "fileSearchStores/store3"

    mock_file_search_service.client.file_search_stores.list = (
        Mock(return_value=[mock_store1, mock_store2, mock_store3])
    )

    # 빈 Store 문서 목록
    (
        mock_file_search_service.client
        .file_search_stores.list_documents
    ) = Mock(return_value=[])

    mock_file_search_service.client.file_search_stores.delete = (
        Mock()
    )

    deleted_count = await service.cleanup_expired_sessions(
        expiry_hours=24
    )

    # 2개의 빈 사용자 Store가 삭제되어야 함
    assert deleted_count == 2


@pytest.mark.asyncio
async def test_list_user_documents_success(
    service, mock_file_search_service
):
    """사용자 문서 목록 조회 테스트"""
    service.file_search_service = mock_file_search_service

    # Mock Store
    mock_store = Mock()
    mock_store.display_name = "user-user123-store"
    mock_store.name = "fileSearchStores/store1"

    mock_file_search_service.client.file_search_stores.list = (
        Mock(return_value=[mock_store])
    )

    # Mock 문서 목록
    mock_doc1 = Mock()
    mock_doc1.name = "fileSearchStores/store1/documents/doc1"
    mock_doc1.display_name = "지도안1.pdf"

    mock_doc2 = Mock()
    mock_doc2.name = "fileSearchStores/store1/documents/doc2"
    mock_doc2.display_name = "지도안2.pdf"

    (
        mock_file_search_service.client
        .file_search_stores.list_documents
    ) = Mock(return_value=[mock_doc1, mock_doc2])

    documents = await service.list_user_documents("user123")

    assert len(documents) == 2
    assert documents[0]["display_name"] == "지도안1.pdf"
    assert documents[1]["display_name"] == "지도안2.pdf"


@pytest.mark.asyncio
async def test_list_user_documents_no_store(
    service, mock_file_search_service
):
    """Store가 없는 경우 문서 목록 조회 테스트"""
    service.file_search_service = mock_file_search_service

    # 빈 Store 리스트
    mock_file_search_service.client.file_search_stores.list = (
        Mock(return_value=[])
    )

    documents = await service.list_user_documents("user123")

    assert len(documents) == 0
