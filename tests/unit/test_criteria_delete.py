"""
평가 기준 삭제 기능 단위 테스트
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

from app.repositories.criteria_repository import CriteriaRepository
from app.models.criteria import CriteriaDocument


@pytest.mark.asyncio
class TestCriteriaDelete:
    """평가 기준 삭제 테스트"""

    async def test_delete_by_id_success(self):
        """개별 삭제 성공 케이스"""
        # Mock DB 세션
        mock_db = AsyncMock()

        # Mock 문서
        mock_doc = CriteriaDocument(
            id=1,
            title="테스트 문서",
            file_path="/tmp/test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            vector_store_id="test_store_123",
            status="uploaded",
        )

        # Repository 생성
        repo = CriteriaRepository(mock_db)

        # get_by_id 모킹
        with patch.object(
            repo, "get_by_id", return_value=mock_doc
        ):
            # 삭제 실행
            deleted_doc = await repo.delete_by_id(1)

            # 검증
            assert deleted_doc is not None
            assert deleted_doc.id == 1
            assert deleted_doc.title == "테스트 문서"

    async def test_delete_by_id_not_found(self):
        """존재하지 않는 문서 삭제"""
        mock_db = AsyncMock()
        repo = CriteriaRepository(mock_db)

        # get_by_id가 None 반환하도록 모킹
        with patch.object(repo, "get_by_id", return_value=None):
            deleted_doc = await repo.delete_by_id(999)

            # 검증
            assert deleted_doc is None

    async def test_delete_by_id_active_document(self):
        """활성 상태인 문서 삭제"""
        mock_db = AsyncMock()

        # 활성 문서 모킹
        mock_doc = CriteriaDocument(
            id=1,
            title="활성 문서",
            file_path="/tmp/active.pdf",
            mime_type="application/pdf",
            file_size=2048,
            vector_store_id="active_store_123",
            status="active",
        )

        repo = CriteriaRepository(mock_db)

        with patch.object(
            repo, "get_by_id", return_value=mock_doc
        ):
            deleted_doc = await repo.delete_by_id(1)

            # 검증
            assert deleted_doc is not None
            assert deleted_doc.status == "active"
            # active_criteria 테이블 업데이트가 호출되어야 함
            assert mock_db.execute.called

    async def test_delete_all_success(self):
        """전체 삭제 성공 케이스"""
        mock_db = AsyncMock()

        # 전체 개수 조회 결과 모킹
        mock_count_result = Mock()
        mock_count_result.scalar.return_value = 5

        # execute 호출 시 count 결과 반환
        mock_db.execute.return_value = mock_count_result

        repo = CriteriaRepository(mock_db)

        # 삭제 실행
        deleted_count = await repo.delete_all()

        # 검증
        assert deleted_count == 5
        assert mock_db.execute.called
        assert mock_db.flush.called

    async def test_delete_all_empty_database(self):
        """문서가 없는 경우 전체 삭제"""
        mock_db = AsyncMock()

        # 전체 개수 0으로 모킹
        mock_count_result = Mock()
        mock_count_result.scalar.return_value = 0

        mock_db.execute.return_value = mock_count_result

        repo = CriteriaRepository(mock_db)

        # 삭제 실행
        deleted_count = await repo.delete_all()

        # 검증
        assert deleted_count == 0


@pytest.mark.asyncio
class TestCriteriaDeleteAPI:
    """평가 기준 삭제 API 테스트"""

    async def test_delete_criteria_endpoint(self):
        """DELETE /admin/criteria/{id} 엔드포인트 테스트"""
        from fastapi.testclient import TestClient
        from app.main import app

        # TestClient는 동기 방식이므로 주의
        # 실제 통합 테스트는 별도 파일에서 수행
        pass

    async def test_delete_all_criteria_endpoint(self):
        """DELETE /admin/criteria/ 엔드포인트 테스트"""
        # 통합 테스트는 별도 파일에서 수행
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
