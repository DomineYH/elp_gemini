"""
CriteriaRepository 활성화 기능 단위 테스트
activate_criteria(), deactivate_all() 트랜잭션 검증
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.criteria_repository import (
    CriteriaRepository
)
from app.models.criteria import CriteriaDocument, ActiveCriteria


@pytest.fixture
def mock_db():
    """Mock AsyncSession 생성"""
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def repository(mock_db):
    """CriteriaRepository 인스턴스 생성"""
    return CriteriaRepository(db=mock_db)


@pytest.mark.asyncio
class TestCriteriaRepositoryActivation:
    """activate_criteria(), deactivate_all() 테스트"""

    async def test_activate_criteria_success(
        self, repository, mock_db
    ):
        """정상 활성화 트랜잭션 테스트"""
        # Arrange
        criteria_id = 1
        admin_id = 100

        # 활성화할 문서
        mock_doc = CriteriaDocument(
            id=criteria_id,
            title="Test",
            file_path="/test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            vector_store_id="store-123",
            status="uploaded",
        )

        # get_by_id 모킹
        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = (
            mock_doc
        )

        # active_criteria 조회 모킹
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = (
            None
        )

        mock_db.execute.side_effect = [
            get_result,  # get_by_id
            AsyncMock(),  # update old active
            active_result,  # get active_criteria
        ]

        # Act
        result = await repository.activate_criteria(
            criteria_id, admin_id
        )

        # Assert
        assert result.status == "active"
        assert result.activated_at is not None
        assert result.activated_by == admin_id
        assert mock_db.execute.await_count == 3
        mock_db.add.assert_called_once()

    async def test_activate_criteria_not_found(
        self, repository, mock_db
    ):
        """존재하지 않는 문서 활성화 시도"""
        # Arrange
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Act & Assert
        with pytest.raises(ValueError) as exc:
            await repository.activate_criteria(
                999, 100
            )

        assert "not found" in str(exc.value)

    async def test_activate_criteria_update_existing(
        self, repository, mock_db
    ):
        """기존 활성 문서 교체 테스트"""
        # Arrange
        new_criteria_id = 2
        admin_id = 100

        # 새로 활성화할 문서
        new_doc = CriteriaDocument(
            id=new_criteria_id,
            title="New",
            file_path="/new.pdf",
            mime_type="application/pdf",
            file_size=2048,
            vector_store_id="store-456",
            status="uploaded",
        )

        # 기존 활성 레코드
        existing_active = ActiveCriteria(
            id=1,
            criteria_document_id=1,
            activated_at=datetime.utcnow(),
            activated_by=99,
        )

        # get_by_id 모킹
        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = (
            new_doc
        )

        # active_criteria 조회 모킹
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = (
            existing_active
        )

        mock_db.execute.side_effect = [
            get_result,  # get_by_id
            AsyncMock(),  # update old active
            active_result,  # get active_criteria
        ]

        # Act
        result = await repository.activate_criteria(
            new_criteria_id, admin_id
        )

        # Assert
        assert result.status == "active"
        assert result.activated_by == admin_id
        # 기존 레코드가 업데이트되어야 함
        assert (
            existing_active.criteria_document_id
            == new_criteria_id
        )
        assert existing_active.activated_by == admin_id
        mock_db.add.assert_not_called()

    async def test_deactivate_all_success(
        self, repository, mock_db
    ):
        """정상 비활성화 테스트"""
        # Arrange
        mock_doc = CriteriaDocument(
            id=1,
            title="Active",
            file_path="/test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            vector_store_id="store-123",
            status="active",
        )

        mock_active = ActiveCriteria(
            id=1,
            criteria_document_id=1,
            activated_at=datetime.utcnow(),
            activated_by=100,
        )

        # get_active 모킹
        active_doc_result = MagicMock()
        active_doc_result.scalar_one_or_none.return_value = (
            mock_doc
        )

        # active_criteria 조회 모킹
        active_record_result = MagicMock()
        active_record_result.scalar_one_or_none.return_value = (
            mock_active
        )

        mock_db.execute.side_effect = [
            active_doc_result,
            active_record_result,
        ]

        # Act
        result = await repository.deactivate_all()

        # Assert
        assert result == 1
        assert mock_doc.status == "uploaded"
        assert mock_doc.activated_at is None
        assert mock_active.criteria_document_id is None

    async def test_deactivate_all_no_active(
        self, repository, mock_db
    ):
        """활성 문서가 없을 때 비활성화"""
        # Arrange
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Act
        result = await repository.deactivate_all()

        # Assert
        assert result is None
        mock_db.flush.assert_not_awaited()

    async def test_deactivate_all_cleanup_fields(
        self, repository, mock_db
    ):
        """비활성화 시 모든 필드 정리 검증"""
        # Arrange
        mock_doc = CriteriaDocument(
            id=1,
            title="Active",
            file_path="/test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            vector_store_id="store-123",
            status="active",
            activated_at=datetime.utcnow(),
            activated_by=100,
        )

        mock_active = ActiveCriteria(
            id=1,
            criteria_document_id=1,
            activated_at=datetime.utcnow(),
            activated_by=100,
        )

        # get_active 모킹
        active_doc_result = MagicMock()
        active_doc_result.scalar_one_or_none.return_value = (
            mock_doc
        )

        # active_criteria 조회 모킹
        active_record_result = MagicMock()
        active_record_result.scalar_one_or_none.return_value = (
            mock_active
        )

        mock_db.execute.side_effect = [
            active_doc_result,
            active_record_result,
        ]

        # Act
        result = await repository.deactivate_all()

        # Assert
        assert result == 1
        # 문서 필드 정리 확인
        assert mock_doc.status == "uploaded"
        assert mock_doc.activated_at is None
        assert mock_doc.activated_by is None
        # active_criteria 레코드 정리 확인
        assert mock_active.criteria_document_id is None
        assert mock_active.activated_at is None
        assert mock_active.activated_by is None
        # DB 플러시 확인
        mock_db.flush.assert_awaited_once()
