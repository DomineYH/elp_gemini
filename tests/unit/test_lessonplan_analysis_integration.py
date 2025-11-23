"""
LessonPlanAnalysis 통합 테스트
API 엔드포인트 검증
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from httpx import AsyncClient
from app.main import app


@pytest.mark.integration
class TestLessonPlanAnalysisIntegration:
    """
    API 엔드포인트 통합 테스트
    """

    @pytest.fixture
    def mock_user(self):
        """Mock 현재 사용자"""
        user = Mock()
        user.id = 42
        user.username = "testuser"
        user.email = "test@example.com"
        return user

    @pytest.mark.asyncio
    async def test_analyze_endpoint_success(
        self,
        mock_user
    ):
        """
        POST /api/lessonplan/analyze 성공 (200)
        """
        # Mock get_current_user
        async def mock_get_current_user():
            return mock_user

        # Mock get_db
        async def mock_get_db():
            yield AsyncMock()

        # Mock LessonPlanAnalysisService
        mock_service_instance = AsyncMock()
        mock_service_instance.analyze_lesson_plan = AsyncMock(
            return_value={
                "success": True,
                "report": "# 📚 수업 지도안 평가 보고서\n\n...",
                "citations": {
                    "grounding_chunks": []
                },
                "latency_ms": 12350
            }
        )

        with patch(
            'app.routers.lessonplan_analysis.get_current_user',
            mock_get_current_user
        ):
            with patch(
                'app.routers.lessonplan_analysis.get_db',
                mock_get_db
            ):
                with patch(
                    'app.routers.lessonplan_analysis'
                    '.LessonPlanAnalysisService',
                    return_value=mock_service_instance
                ):
                    async with AsyncClient(
                        app=app,
                        base_url="http://test"
                    ) as client:
                        # When
                        response = await client.post(
                            "/api/lessonplan/analyze",
                            json={"session_id": 1}
                        )

                    # Then
                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert "report" in data
                    assert (
                        "수업 지도안 평가 보고서"
                        in data["report"]
                    )

    @pytest.mark.asyncio
    async def test_analyze_endpoint_unauthorized(
        self
    ):
        """
        인증 실패 (401)
        """
        # Mock get_current_user - 인증 실패
        async def mock_get_current_user_fail():
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="인증되지 않은 사용자"
            )

        with patch(
            'app.routers.lessonplan_analysis.get_current_user',
            mock_get_current_user_fail
        ):
            async with AsyncClient(
                app=app,
                base_url="http://test"
            ) as client:
                # When
                response = await client.post(
                    "/api/lessonplan/analyze",
                    json={"session_id": 1}
                )

            # Then
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_analyze_endpoint_invalid_session(
        self,
        mock_user
    ):
        """
        잘못된 세션 ID (422)
        """
        # Mock get_current_user
        async def mock_get_current_user():
            return mock_user

        with patch(
            'app.routers.lessonplan_analysis.get_current_user',
            mock_get_current_user
        ):
            async with AsyncClient(
                app=app,
                base_url="http://test"
            ) as client:
                # When - session_id가 음수
                response = await client.post(
                    "/api/lessonplan/analyze",
                    json={"session_id": -1}
                )

            # Then
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_endpoint_service_error(
        self,
        mock_user
    ):
        """
        서비스 에러 발생 시 500 반환
        """
        # Mock get_current_user
        async def mock_get_current_user():
            return mock_user

        # Mock get_db
        async def mock_get_db():
            yield AsyncMock()

        # Mock LessonPlanAnalysisService - 에러 반환
        mock_service_instance = AsyncMock()
        mock_service_instance.analyze_lesson_plan = AsyncMock(
            return_value={
                "success": False,
                "error": "분석 중 오류 발생"
            }
        )

        with patch(
            'app.routers.lessonplan_analysis.get_current_user',
            mock_get_current_user
        ):
            with patch(
                'app.routers.lessonplan_analysis.get_db',
                mock_get_db
            ):
                with patch(
                    'app.routers.lessonplan_analysis'
                    '.LessonPlanAnalysisService',
                    return_value=mock_service_instance
                ):
                    async with AsyncClient(
                        app=app,
                        base_url="http://test"
                    ) as client:
                        # When
                        response = await client.post(
                            "/api/lessonplan/analyze",
                            json={"session_id": 1}
                        )

                    # Then
                    assert response.status_code == 500
