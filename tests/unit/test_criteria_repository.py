"""
CriteriaRepository 단위 테스트
CRUD 작업, 활성화 트랜잭션, 상태 관리 검증
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

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
class TestCriteriaRepositoryCreate:
    """create() 메서드 테스트"""

    async def test_create_success(
        self, repository, mock_db
    ):
        """정상적인 문서 생성 테스트"""
        # Arrange
        title = "Test Criteria"
        file_path = "/uploads/test.pdf"
        mime_type = "application/pdf"
        file_size = 1024
        vector_store_id = "store-123"

        # Act
        result = await repository.create(
            title=title,
            file_path=file_path,
            mime_type=mime_type,
            file_size=file_size,
            vector_store_id=vector_store_id,
        )

        # Assert
        assert result.title == title
        assert result.file_path == file_path
        assert result.mime_type == mime_type
        assert result.file_size == file_size
        assert result.vector_store_id == vector_store_id
        assert result.status == "uploaded"

        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    async def test_create_duplicate_vector_store_id(
        self, repository, mock_db
    ):
        """중복 vector_store_id 테스트"""
        # Arrange
        mock_db.flush.side_effect = IntegrityError(
            "duplicate", {}, None
        )

        # Act & Assert
        with pytest.raises(IntegrityError):
            await repository.create(
                title="Test",
                file_path="/test.pdf",
                mime_type="application/pdf",
                file_size=1024,
                vector_store_id="duplicate-id",
            )


@pytest.mark.asyncio
class TestCriteriaRepositoryGetById:
    """get_by_id() 메서드 테스트"""

    async def test_get_by_id_exists(
        self, repository, mock_db
    ):
        """존재하는 문서 조회 테스트"""
        # Arrange
        criteria_id = 1
        mock_doc = CriteriaDocument(
            id=criteria_id,
            title="Test Criteria",
            file_path="/test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            vector_store_id="store-123",
            status="uploaded",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = (
            mock_doc
        )
        mock_db.execute.return_value = mock_result

        # Act
        result = await repository.get_by_id(criteria_id)

        # Assert
        assert result == mock_doc
        assert result.id == criteria_id
        mock_db.execute.assert_awaited_once()

    async def test_get_by_id_not_exists(
        self, repository, mock_db
    ):
        """존재하지 않는 문서 조회 테스트"""
        # Arrange
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Act
        result = await repository.get_by_id(999)

        # Assert
        assert result is None
        mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
class TestCriteriaRepositoryListAll:
    """list_all() 메서드 테스트"""

    async def test_list_all_with_pagination(
        self, repository, mock_db
    ):
        """페이지네이션 목록 조회 테스트"""
        # Arrange
        mock_docs = [
            CriteriaDocument(
                id=i,
                title=f"Doc {i}",
                file_path=f"/doc{i}.pdf",
                mime_type="application/pdf",
                file_size=1024,
                vector_store_id=f"store-{i}",
                status="uploaded",
            )
            for i in range(1, 6)
        ]

        # Count 쿼리 결과
        count_result = MagicMock()
        count_result.scalar.return_value = 15

        # List 쿼리 결과
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = (
            mock_docs
        )

        mock_db.execute.side_effect = [
            count_result, list_result
        ]

        # Act
        documents, total = await repository.list_all(
            page=1, page_size=5
        )

        # Assert
        assert len(documents) == 5
        assert total == 15
        assert mock_db.execute.await_count == 2

    async def test_list_all_empty(
        self, repository, mock_db
    ):
        """빈 목록 조회 테스트"""
        # Arrange
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = (
            []
        )

        mock_db.execute.side_effect = [
            count_result, list_result
        ]

        # Act
        documents, total = await repository.list_all(
            page=1, page_size=20
        )

        # Assert
        assert len(documents) == 0
        assert total == 0


@pytest.mark.asyncio
class TestCriteriaRepositoryUpdateStatus:
    """update_status() 메서드 테스트"""

    async def test_update_status_success(
        self, repository, mock_db
    ):
        """정상 상태 업데이트 테스트"""
        # Arrange
        criteria_id = 1
        new_status = "active"

        mock_doc = CriteriaDocument(
            id=criteria_id,
            title="Test",
            file_path="/test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            vector_store_id="store-123",
            status="uploaded",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = (
            mock_doc
        )
        mock_db.execute.return_value = mock_result

        # Act
        result = await repository.update_status(
            criteria_id, new_status
        )

        # Assert
        assert result.status == new_status
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    async def test_update_status_invalid(
        self, repository, mock_db
    ):
        """유효하지 않은 상태값 테스트"""
        # Arrange
        invalid_status = "invalid_status"

        # Act & Assert
        with pytest.raises(ValueError) as exc:
            await repository.update_status(
                1, invalid_status
            )

        assert "Invalid status" in str(exc.value)
        mock_db.flush.assert_not_awaited()

    async def test_update_status_not_found(
        self, repository, mock_db
    ):
        """존재하지 않는 문서 상태 업데이트"""
        # Arrange
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Act
        result = await repository.update_status(
            999, "active"
        )

        # Assert
        assert result is None
        mock_db.flush.assert_not_awaited()


@pytest.mark.asyncio
class TestCriteriaRepositoryGetActive:
    """get_active() 메서드 테스트"""

    async def test_get_active_exists(
        self, repository, mock_db
    ):
        """활성 문서 조회 테스트"""
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

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = (
            mock_doc
        )
        mock_db.execute.return_value = mock_result

        # Act
        result = await repository.get_active()

        # Assert
        assert result == mock_doc
        assert result.status == "active"

    async def test_get_active_none(
        self, repository, mock_db
    ):
        """활성 문서가 없을 때"""
        # Arrange
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Act
        result = await repository.get_active()

        # Assert
        assert result is None

