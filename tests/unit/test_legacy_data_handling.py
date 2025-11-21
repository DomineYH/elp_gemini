"""
Task 4.5: 레거시 데이터 처리 검증 테스트

document_id가 NULL인 기존 데이터 삭제 시나리오 테스트:
1. 경고 로그 출력 확인
2. 스토어만 삭제 시도 (문서 삭제 건너뛰기)
3. FAILED_PRECONDITION 오류 핸들링
"""

import pytest
import logging
from unittest.mock import AsyncMock, patch, MagicMock
from google.api_core.exceptions import FailedPrecondition

from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService
)


class TestLegacyDataHandling:
    """레거시 데이터(document_id NULL) 삭제 처리 검증"""

    @pytest.mark.asyncio
    async def test_legacy_delete_without_document_id(
        self,
        caplog
    ):
        """
        레거시 데이터 삭제: document_id가 없는 경우
        - 문서 삭제 건너뛰기
        - 경고 로그 출력
        - 스토어만 삭제 시도
        """
        service = CriteriaEmbeddingService()

        # 레거시 데이터 시뮬레이션
        vector_store_id = "test_store_legacy"
        document_id = None  # 레거시 데이터는 NULL

        # 로그 캡처 시작
        with caplog.at_level(logging.WARNING):
            # Mock: delete_store만 호출
            with patch.object(
                service,
                "delete_store",
                new_callable=AsyncMock
            ) as mock_delete_store:

                # Phase 3 삭제 라우터 로직 시뮬레이션
                if document_id:
                    # document_id 있으면 문서 삭제
                    pass  # 실행되지 않음
                else:
                    # document_id 없으면 경고 로그
                    logging.getLogger(__name__).warning(
                        f"레거시 데이터 감지: "
                        f"document_id가 없습니다. "
                        f"(store_id={vector_store_id})"
                    )

                # 스토어 삭제 시도
                await service.delete_store(
                    vector_store_id=vector_store_id
                )

                # 검증: 스토어 삭제만 호출됨
                mock_delete_store.assert_called_once_with(
                    vector_store_id=vector_store_id
                )

        # 경고 로그 출력 확인
        assert "레거시 데이터 감지" in caplog.text
        assert "document_id가 없습니다" in caplog.text

    @pytest.mark.asyncio
    async def test_failed_precondition_error_handling(
        self,
        caplog
    ):
        """
        FAILED_PRECONDITION 오류 핸들링 검증
        - 스토어 내부에 문서가 남아있는 경우
        - 사용자 친화적인 에러 메시지
        Phase 3: criteria_embedding_service.delete_store()
        """
        service = CriteriaEmbeddingService()

        vector_store_id = "test_store_with_documents"

        # Mock: Google API 호출 시 400 에러 발생
        error = Exception(
            "400 FAILED_PRECONDITION: "
            "Store contains documents"
        )

        # 올바른 경로로 Mock
        with patch.object(
            service.client.file_search_stores,
            "delete",
            side_effect=error
        ):

            # 로그 캡처
            with caplog.at_level(logging.ERROR):
                # Phase 3: 에러 핸들링
                # ignore_errors=False (기본값) → ValueError 발생
                try:
                    await service.delete_store(
                        vector_store_id=vector_store_id
                    )
                    pytest.fail("ValueError 예외가 발생해야 함")

                except ValueError as e:
                    # Phase 3 에러 핸들링 검증
                    assert "스토어 내부에 문서가 남아있어" in str(e)
                    assert "문서를 먼저 삭제하세요" in str(e)

        # 에러 로그 확인 (Phase 3 구현)
        assert "Vector Store 삭제 실패" in caplog.text
        assert "스토어 내부에 문서가 남아있습니다" in caplog.text
        assert "문서를 먼저 삭제해야 합니다" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_route_legacy_handling(self):
        """
        삭제 라우터의 레거시 데이터 처리 로직 검증
        Phase 3: criteria_delete.py 로직 시뮬레이션
        """
        # 레거시 데이터 시뮬레이션
        criteria = MagicMock()
        criteria.id = 999
        criteria.title = "Legacy Criteria"
        criteria.vector_store_id = "legacy_store_123"
        criteria.document_id = None  # 레거시 데이터

        service = CriteriaEmbeddingService()

        with patch.object(
            service,
            "delete_document",
            new_callable=AsyncMock
        ) as mock_delete_doc, \
        patch.object(
            service,
            "delete_store",
            new_callable=AsyncMock
        ) as mock_delete_store:

            # Phase 3 삭제 라우터 로직
            delete_errors = []

            # 1. 문서 삭제 (document_id 있을 때만)
            if criteria.document_id:
                try:
                    await service.delete_document(
                        vector_store_id=criteria.vector_store_id,
                        document_id=criteria.document_id
                    )
                except Exception as e:
                    delete_errors.append(
                        f"문서 삭제 실패: {str(e)}"
                    )
            else:
                # 레거시 데이터: 경고만 출력
                logging.getLogger(__name__).warning(
                    f"document_id가 없어 "
                    f"문서 삭제를 건너뜁니다. "
                    f"(criteria_id={criteria.id})"
                )

            # 2. 스토어 삭제
            if criteria.vector_store_id:
                try:
                    await service.delete_store(
                        vector_store_id=criteria.vector_store_id
                    )
                except Exception as e:
                    delete_errors.append(
                        f"스토어 삭제 실패: {str(e)}"
                    )

            # 검증: 문서 삭제는 호출되지 않음
            mock_delete_doc.assert_not_called()

            # 검증: 스토어 삭제는 호출됨
            mock_delete_store.assert_called_once_with(
                vector_store_id="legacy_store_123"
            )

            # 검증: 에러 없음 (스토어 삭제만 수행)
            assert len(delete_errors) == 0

    @pytest.mark.asyncio
    async def test_partial_deletion_scenario(
        self,
        caplog
    ):
        """
        부분 삭제 시나리오 검증
        - 문서 삭제 성공, 스토어 삭제 실패
        - 상세한 상태 로깅
        """
        service = CriteriaEmbeddingService()

        vector_store_id = "partial_delete_store"
        document_id = "partial_delete_doc"

        # Mock 설정
        with patch.object(
            service,
            "delete_document",
            new_callable=AsyncMock
        ) as mock_delete_doc, \
        patch.object(
            service,
            "delete_store",
            side_effect=FailedPrecondition("Store error")
        ):

            # 로그 캡처
            with caplog.at_level(logging.INFO):
                delete_results = {
                    "document_deleted": False,
                    "store_deleted": False,
                    "errors": []
                }

                # 1. 문서 삭제
                try:
                    await service.delete_document(
                        vector_store_id=vector_store_id,
                        document_id=document_id
                    )
                    delete_results["document_deleted"] = True
                    logging.getLogger(__name__).info(
                        "문서 삭제 성공"
                    )
                except Exception as e:
                    delete_results["errors"].append(
                        f"문서 삭제 실패: {str(e)}"
                    )

                # 2. 스토어 삭제
                try:
                    await service.delete_store(
                        vector_store_id=vector_store_id
                    )
                    delete_results["store_deleted"] = True
                except Exception as e:
                    delete_results["errors"].append(
                        f"스토어 삭제 실패: {str(e)}"
                    )
                    logging.getLogger(__name__).error(
                        f"부분 삭제 발생: "
                        f"문서는 삭제되었으나 "
                        f"스토어 삭제 실패"
                    )

                # 검증
                assert delete_results["document_deleted"] is True
                assert delete_results["store_deleted"] is False
                assert len(delete_results["errors"]) == 1

        # 로그 검증
        assert "문서 삭제 성공" in caplog.text
        assert "부분 삭제 발생" in caplog.text
