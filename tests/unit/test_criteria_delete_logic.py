"""
평가기준 삭제 로직 테스트
Phase 3 변경사항 검증: 문서→스토어 순차 삭제
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from contextlib import contextmanager
from app.routers.admin.criteria_delete import (
    delete_criteria,
    delete_all_criteria
)
from app.models.users import User
from app.models.criteria import CriteriaDocument


@contextmanager
def patch_delete_dependencies(
    mock_repo, mock_embedding_service, mock_audit_service
):
    """삭제 테스트 공통 의존성 패치"""
    with patch(
        "app.routers.admin.criteria_delete.CriteriaRepository",
        return_value=mock_repo
    ), patch(
        "app.routers.admin.criteria_delete."
        "CriteriaEmbeddingService",
        return_value=mock_embedding_service
    ), patch(
        "app.routers.admin.criteria_delete."
        "CriteriaAuditService",
        return_value=mock_audit_service
    ), patch(
        "app.routers.admin.criteria_delete.os.remove"
    ), patch(
        "app.routers.admin.criteria_delete.Path"
    ) as mock_path:
        mock_path_instance = Mock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance
        yield


@pytest.mark.asyncio
async def test_delete_with_document_id_sequential():
    """
    document_id가 있는 경우:
    문서 삭제 → 스토어 삭제 순서 검증
    """
    # Arrange
    mock_db = AsyncMock()
    mock_user = User(
        id=1, is_admin=True
    )

    mock_repo = AsyncMock()
    mock_doc = CriteriaDocument(
        id=1,
        title="Test Doc",
        file_path="/tmp/test.pdf",
        vector_store_id="store_123",
        document_id="docs/doc_456",
        status="uploaded"
    )
    mock_repo.get_by_id.return_value = mock_doc
    mock_repo.delete_by_id.return_value = mock_doc

    mock_embedding_service = AsyncMock()
    mock_embedding_service.delete_document.return_value = True
    mock_embedding_service.delete_store.return_value = True

    mock_audit_service = AsyncMock()

    with patch_delete_dependencies(
        mock_repo, mock_embedding_service, mock_audit_service
    ):
        # Act
        response = await delete_criteria(
            criteria_id=1,
            current_user=mock_user,
            db=mock_db
        )

        # Assert
        assert response.success is True

        # Phase 3: 순차 삭제 검증
        mock_embedding_service.delete_document.\
            assert_called_once_with(
                vector_store_id="store_123",
                document_id="docs/doc_456",
                ignore_errors=False
            )
        mock_embedding_service.delete_store.\
            assert_called_once_with(
                "store_123",
                ignore_errors=False
            )

        # 호출 순서 검증 (문서 → 스토어)
        calls = mock_embedding_service.method_calls
        doc_idx = next(
            (i for i, c in enumerate(calls)
             if c[0] == 'delete_document'),
            None
        )
        store_idx = next(
            (i for i, c in enumerate(calls)
             if c[0] == 'delete_store'),
            None
        )

        assert doc_idx is not None
        assert store_idx is not None
        assert doc_idx < store_idx

        mock_repo.delete_by_id.assert_called_once_with(1)
        mock_audit_service.log_delete.assert_called_once()


@pytest.mark.asyncio
async def test_delete_without_document_id_legacy():
    """
    document_id가 없는 경우 (레거시 데이터):
    경고 로그 출력 및 스토어만 삭제
    """
    # Arrange
    mock_db = AsyncMock()
    mock_user = User(
        id=1, is_admin=True
    )

    mock_repo = AsyncMock()
    mock_doc = CriteriaDocument(
        id=1,
        title="Legacy Doc",
        file_path="/tmp/legacy.pdf",
        vector_store_id="store_legacy",
        document_id=None,  # 레거시: document_id 없음
        status="uploaded"
    )
    mock_repo.get_by_id.return_value = mock_doc
    mock_repo.delete_by_id.return_value = mock_doc

    mock_embedding_service = AsyncMock()
    mock_embedding_service.delete_store.return_value = True

    mock_audit_service = AsyncMock()

    with patch_delete_dependencies(
        mock_repo, mock_embedding_service, mock_audit_service
    ):
        # Act
        response = await delete_criteria(
            criteria_id=1,
            current_user=mock_user,
            db=mock_db
        )

        # Assert
        assert response.success is True

        # Phase 3: 레거시 데이터 처리 검증
        # delete_document() 호출되지 않아야 함
        mock_embedding_service.delete_document.\
            assert_not_called()

        # delete_store()만 호출되어야 함
        mock_embedding_service.delete_store.\
            assert_called_once_with(
                "store_legacy",
                ignore_errors=False
            )

        mock_repo.delete_by_id.assert_called_once_with(1)
        mock_audit_service.log_delete.assert_called_once()


@pytest.mark.asyncio
async def test_delete_all_criteria_sequential():
    """
    전체 삭제 시:
    각 문서에 대해 문서→스토어 순차 삭제 검증
    """
    # Arrange
    mock_db = AsyncMock()
    mock_user = User(
        id=1, is_admin=True
    )

    mock_repo = AsyncMock()
    mock_docs = [
        CriteriaDocument(
            id=1,
            title="Doc 1",
            file_path="/tmp/doc1.pdf",
            vector_store_id="store_1",
            document_id="docs/doc_1",
            status="uploaded"
        ),
        CriteriaDocument(
            id=2,
            title="Doc 2",
            file_path="/tmp/doc2.pdf",
            vector_store_id="store_2",
            document_id="docs/doc_2",
            status="uploaded"
        )
    ]
    mock_repo.list_all.return_value = (mock_docs, 2)
    mock_repo.delete_all.return_value = 2

    mock_embedding_service = AsyncMock()
    mock_embedding_service.delete_document.return_value = True
    mock_embedding_service.delete_store.return_value = True

    mock_audit_service = AsyncMock()

    with patch_delete_dependencies(
        mock_repo, mock_embedding_service, mock_audit_service
    ):
        # Act
        response = await delete_all_criteria(
            current_user=mock_user, db=mock_db
        )

        # Assert
        assert response.success is True

        # Phase 3: 순차 삭제 검증
        # 각 문서에 대해 delete_document() 호출
        assert (
            mock_embedding_service.delete_document.call_count
            == 2
        )
        mock_embedding_service.delete_document.\
            assert_any_call(
                vector_store_id="store_1",
                document_id="docs/doc_1",
                ignore_errors=False
            )
        mock_embedding_service.delete_document.\
            assert_any_call(
                vector_store_id="store_2",
                document_id="docs/doc_2",
                ignore_errors=False
            )

        # 각 스토어에 대해 delete_store() 호출
        assert (
            mock_embedding_service.delete_store.call_count == 2
        )
        mock_embedding_service.delete_store.assert_any_call(
            "store_1",
            ignore_errors=False
        )
        mock_embedding_service.delete_store.assert_any_call(
            "store_2",
            ignore_errors=False
        )
