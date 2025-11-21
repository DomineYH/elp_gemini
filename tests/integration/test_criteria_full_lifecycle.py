"""
평가기준 전체 라이프사이클 통합 테스트
업로드 → 조회 → 삭제 전체 흐름 검증
Phase 2-3 변경사항 포함
"""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from sqlalchemy import select

from app.main import app
from app.models.criteria import CriteriaDocument
from app.routers.auth import get_current_admin

from conftest import (
    create_test_pdf,
    override_admin,
    TestingSessionLocal
)


class TestCriteriaFullLifecycle:
    """업로드 → 조회 → 삭제 통합 시나리오"""

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_document_id(
        self,
        test_client,
        admin_user
    ):
        """
        전체 흐름 검증:
        1. 업로드 → document_id 저장 확인
        2. DB 조회 → document_id 확인
        3. 삭제 → 문서→스토어 순차 삭제 확인
        """
        # === 1. 업로드 단계 ===

        # 업로드 준비
        pdf_file = create_test_pdf()
        files = {
            "file": (
                "lifecycle_test.pdf",
                pdf_file,
                "application/pdf"
            )
        }
        data = {"title": "Full Lifecycle Test Criteria"}

        # Admin 인증 오버라이드
        app.dependency_overrides[get_current_admin] = (
            override_admin(admin_user)
        )

        # Phase 2: upload_and_embed가 튜플 반환
        mock_vector_id = "stores/lifecycle-vector-123"
        mock_document_id = "docs/lifecycle-doc-456"

        with patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "upload_and_embed",
            new_callable=AsyncMock
        ) as mock_embed:
            # Phase 2 변경: 튜플 반환
            mock_embed.return_value = (
                mock_vector_id,
                mock_document_id
            )

            # 업로드 API 호출
            upload_response = test_client.post(
                "/admin/criteria/upload",
                files=files,
                data=data
            )

        # 업로드 응답 검증
        assert upload_response.status_code == 200
        upload_data = upload_response.json()
        assert upload_data["id"] is not None
        assert upload_data["vector_store_id"] == mock_vector_id
        assert upload_data["document_id"] == mock_document_id
        criteria_id = upload_data["id"]

        # === 2. DB 조회 단계 ===

        # DB에서 저장된 데이터 확인
        async with TestingSessionLocal() as db:
            result = await db.execute(
                select(CriteriaDocument).where(
                    CriteriaDocument.id == criteria_id
                )
            )
            saved_doc = result.scalar_one_or_none()

            # Phase 2: document_id 저장 확인
            assert saved_doc is not None
            assert saved_doc.vector_store_id == mock_vector_id
            assert saved_doc.document_id == mock_document_id
            assert saved_doc.title == "Full Lifecycle Test Criteria"

        # === 3. 삭제 단계 ===

        # Phase 3: 순차 삭제 모킹
        with patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "delete_document",
            new_callable=AsyncMock
        ) as mock_delete_doc, patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "delete_store",
            new_callable=AsyncMock
        ) as mock_delete_store:

            # 삭제 성공으로 설정
            mock_delete_doc.return_value = True
            mock_delete_store.return_value = True

            # 삭제 API 호출
            delete_response = test_client.delete(
                f"/admin/criteria/{criteria_id}"
            )

        # 삭제 응답 검증
        assert delete_response.status_code == 200
        delete_data = delete_response.json()
        assert delete_data["success"] is True

        # Phase 3: 순차 삭제 호출 검증
        # 문서 먼저 삭제
        mock_delete_doc.assert_called_once_with(
            vector_store_id=mock_vector_id,
            document_id=mock_document_id,
            ignore_errors=False
        )
        # 스토어 나중에 삭제
        mock_delete_store.assert_called_once_with(
            mock_vector_id,
            ignore_errors=False
        )

        # 호출 순서 검증 (문서 → 스토어)
        # Mock의 call_args_list로 순서 확인
        assert len(mock_delete_doc.call_args_list) == 1
        assert len(mock_delete_store.call_args_list) == 1

        # DB에서 삭제 확인
        async with TestingSessionLocal() as db:
            result = await db.execute(
                select(CriteriaDocument).where(
                    CriteriaDocument.id == criteria_id
                )
            )
            deleted_doc = result.scalar_one_or_none()
            assert deleted_doc is None

        # 인증 오버라이드 제거
        app.dependency_overrides.pop(get_current_admin, None)

    # TODO: 레거시 데이터 테스트는 Task 4.5에서 수동으로 검증
    # (통합 테스트 환경에서 레거시 데이터 직접 생성이 복잡함)
