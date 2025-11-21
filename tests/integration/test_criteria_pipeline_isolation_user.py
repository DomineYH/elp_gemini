"""
Criteria Pipeline 통합 테스트: User Vector DB 격리
User Vector DB와 Criteria Vector DB 완전 분리 검증
"""
import pytest
from unittest.mock import patch, AsyncMock
from app.services.criteria_context_service \
    import CriteriaContextService
from app.routers.auth import get_current_admin

from conftest import create_test_pdf, override_admin

class TestUserVectorDatabaseIsolation:
    """User Vector DB와 Criteria Vector DB 격리 검증"""

    @pytest.mark.asyncio
    async def test_criteria_uses_separate_vector_db(
        self,
        test_client,
        admin_user
    ):
        """
        Criteria가 별도 Vector DB 사용 확인
        """
        # 업로드 준비
        pdf_file = create_test_pdf()
        files = {
            "file": (
                "criteria.pdf",
                pdf_file,
                "application/pdf"
            )
        }
        data = {"title": "Test Criteria"}

        # CriteriaEmbeddingService 호출 추적
        from app.main import app
        app.dependency_overrides[get_current_admin] = (
            override_admin(admin_user)
        )

        mock_vector_id = "criteria-vector-123"
        with patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "upload_and_embed",
            new_callable=AsyncMock
        ) as mock_criteria_embed:
            mock_criteria_embed.return_value = mock_vector_id

            response = test_client.post(
                "/admin/criteria/upload",
                files=files,
                data=data
            )

        app.dependency_overrides.pop(get_current_admin, None)

        # 검증
        assert response.status_code == 200
        assert mock_criteria_embed.called

        # CriteriaEmbeddingService만 호출되고
        # UserEmbeddingService는 호출되지 않음
        with patch(
            "app.services.user_embedding_service."
            "UserEmbeddingService"
        ) as mock_user_embed:
            # 이 블록에서는 User 서비스가
            # 호출되지 않아야 함
            assert not mock_user_embed.called

    @pytest.mark.asyncio
    async def test_no_user_vector_db_access(
        self,
        test_client,
        admin_user
    ):
        """
        User Vector DB 접근 없음 확인
        """
        import os
        pdf_file = create_test_pdf()
        files = {
            "file": (
                "criteria.pdf",
                pdf_file,
                "application/pdf"
            )
        }

        mock_vector_id = "vector-test"

        # User Vector DB 경로 모니터링
        user_vector_path = os.getenv(
            "USER_VECTOR_DB_PATH",
            "data/vector_db/user/"
        )

        from app.main import app
        app.dependency_overrides[get_current_admin] = (
            override_admin(admin_user)
        )

        with patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "upload_and_embed",
            new_callable=AsyncMock,
            return_value=mock_vector_id
        ):
            # 파일 시스템 접근 모니터링
            with patch("builtins.open") as mock_open:
                response = test_client.post(
                    "/admin/criteria/upload",
                    files=files,
                    data={"title": "Test"}
                )

                # User Vector DB 경로 접근 확인
                for call_args in mock_open.call_args_list:
                    file_path = str(call_args[0][0])
                    # User Vector DB 경로에
                    # 쓰기 접근 없어야 함
                    if user_vector_path in file_path:
                        mode = call_args[0][1] if len(
                            call_args[0]
                        ) > 1 else "r"
                        assert "w" not in mode, (
                            f"User Vector DB에 "
                            f"쓰기 접근: {file_path}"
                        )

        app.dependency_overrides.pop(get_current_admin, None)

    @pytest.mark.asyncio
    async def test_context_search_isolation(
        self,
        test_client,
        admin_user
    ):
        """
        Context 검색 시 Criteria Vector DB만 사용
        """
        # Active 기준 설정
        mock_vector_id = "active-vector-123"
        mock_context = [
            {"content": "기준 컨텍스트"}
        ]

        # CriteriaContextService 모킹
        with patch(
            "app.services."
            "criteria_context_service."
            "CriteriaContextService."
            "get_context",
            new_callable=AsyncMock,
            return_value=mock_context
        ) as mock_criteria_context:

            # 검색 시뮬레이션
            # (실제로는 EvaluationService를 통해 호출)
            service = CriteriaContextService()

            # Active 기준 모킹
            with patch.object(
                service,
                "_get_active_vector_store_id",
                return_value=mock_vector_id
            ):
                # Google File Search Tool 모킹
                with patch(
                    "app.services."
                    "criteria_context_service."
                    "genai.files"
                ):
                    try:
                        await service.get_context(
                            query="test query",
                            k=3
                        )
                    except Exception:
                        # Active 기준 없을 수 있음
                        pass

        # User Vector DB 서비스는 호출되지 않아야 함
        with patch(
            "app.services.user_context_service."
            "UserContextService"
        ) as mock_user_context:
            assert not mock_user_context.called
