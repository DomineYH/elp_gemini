"""
LessonPlanAnalysisService 단위 테스트
Phase 3에서 구현된 수업 지도안 분석 기능 검증
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from google.api_core import exceptions
from app.services.lessonplan_analysis_service import (
    LessonPlanAnalysisService
)
from app.config import settings


class TestLessonPlanAnalysisService:
    """
    LessonPlanAnalysisService 테스트
    """

    @pytest.fixture
    def mock_db(self):
        """Mock AsyncSession"""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        """Service 인스턴스 생성"""
        with patch('app.services.lessonplan_analysis_service'
                   '.genai.Client'):
            return LessonPlanAnalysisService(mock_db)

    @pytest.mark.asyncio
    async def test_get_criteria_context_success(
        self,
        service
    ):
        """
        Vector Search 성공 - 평가기준 컨텍스트 추출
        """
        # Mock CriteriaContextService
        service.criteria_service.get_context = AsyncMock(
            return_value={
                "context_text": "평가기준 컨텍스트 내용",
                "criteria_ids": [1, 2, 3]
            }
        )

        # When
        result = await service._get_criteria_context()

        # Then
        assert result == "평가기준 컨텍스트 내용"
        service.criteria_service.get_context \
            .assert_called_once_with(
                "수업 지도안 평가 기준"
            )

    @pytest.mark.asyncio
    async def test_get_criteria_context_failure(
        self,
        service
    ):
        """
        Vector Search 실패 시 기본값 반환
        """
        # Mock CriteriaContextService - 예외 발생
        service.criteria_service.get_context = AsyncMock(
            side_effect=Exception("DB 오류")
        )

        # When
        result = await service._get_criteria_context()

        # Then
        assert result == "평가기준 컨텍스트 없음"

    @pytest.mark.asyncio
    async def test_get_store_ids_success(
        self,
        service
    ):
        """
        Store 조회 성공 - get_dual_store_ids() 사용
        """
        # Mock get_dual_store_ids
        service.file_search_service.get_dual_store_ids = Mock(
            return_value=[
                "fileSearchStores/rubric",
                "fileSearchStores/user123"
            ]
        )

        # When
        result = await service._get_store_ids(user_id=123)

        # Then
        assert len(result) == 2
        assert "fileSearchStores/rubric" in result
        assert "fileSearchStores/user123" in result

    @pytest.mark.asyncio
    async def test_get_store_ids_not_found(
        self,
        service
    ):
        """
        Store 조회 실패 시 빈 리스트 반환
        """
        # Mock get_dual_store_ids - ValueError 발생
        service.file_search_service.get_dual_store_ids = Mock(
            side_effect=ValueError(
                "rubricstore를 찾을 수 없습니다"
            )
        )

        # When
        result = await service._get_store_ids(user_id=123)

        # Then
        assert result == []

    def test_build_analysis_prompt(
        self,
        service
    ):
        """
        프롬프트 구성 확인
        """
        # Given
        system_prompt = "수업 지도안 평가 시스템 프롬프트"
        criteria_context = "평가기준 컨텍스트"

        # When
        result = service._build_analysis_prompt(
            system_prompt,
            criteria_context
        )

        # Then
        assert system_prompt in result
        assert criteria_context in result
        assert "5개 항목" in result
        assert "교육과정 목표" in result
        assert "내용 체계" in result
        assert "교수·학습 방법" in result
        assert "평가 방향" in result
        assert "개선 및 보완" in result

    def test_extract_citations_success(
        self,
        service
    ):
        """
        Citation 추출 성공
        """
        # Mock response with grounding_metadata
        mock_chunk = Mock()
        mock_chunk.retrieved_context = Mock()
        mock_chunk.retrieved_context.uri = "file://doc1"
        mock_chunk.retrieved_context.title = "평가기준1"

        mock_grounding = Mock()
        mock_grounding.grounding_chunks = [mock_chunk]

        mock_candidate = Mock()
        mock_candidate.grounding_metadata = mock_grounding

        mock_response = Mock()
        mock_response.candidates = [mock_candidate]

        # When
        result = service._extract_citations(mock_response)

        # Then
        assert "grounding_chunks" in result
        assert len(result["grounding_chunks"]) == 1
        assert result["grounding_chunks"][0]["uri"] == "file://doc1"
        assert (
            result["grounding_chunks"][0]["title"] == "평가기준1"
        )

    def test_extract_citations_no_grounding(
        self,
        service
    ):
        """
        Grounding 없을 시 빈 딕셔너리 반환
        """
        # Mock response without grounding_metadata
        mock_response = Mock()
        mock_response.candidates = []

        # When
        result = service._extract_citations(mock_response)

        # Then
        assert "grounding_chunks" in result
        assert len(result["grounding_chunks"]) == 0

    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_success(
        self,
        service
    ):
        """
        전체 프로세스 성공
        """
        # Mock _get_criteria_context
        service._get_criteria_context = AsyncMock(
            return_value="평가기준 컨텍스트"
        )

        # Mock _get_store_ids
        service._get_store_ids = AsyncMock(
            return_value=[
                "fileSearchStores/rubric",
                "fileSearchStores/user123"
            ]
        )

        # Mock prompt_loader
        service.prompt_loader.get_prompt = Mock(
            return_value="분석 시스템 프롬프트"
        )

        # Mock Gemini API
        mock_response = Mock()
        mock_response.text = "# 📚 수업 지도안 평가 보고서\n\n..."
        mock_response.candidates = []
        service.client.models.generate_content = Mock(
            return_value=mock_response
        )

        # When
        result = await service.analyze_lesson_plan(
            session_id=1,
            user_id=123
        )

        # Then
        assert result["success"] is True
        assert "report" in result
        assert "수업 지도안 평가 보고서" in result["report"]
        assert "citations" in result
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_no_stores(
        self,
        service
    ):
        """
        Store 없을 시 에러 반환
        """
        # Mock _get_criteria_context
        service._get_criteria_context = AsyncMock(
            return_value="평가기준 컨텍스트"
        )

        # Mock _get_store_ids - 빈 리스트 반환
        service._get_store_ids = AsyncMock(
            return_value=[]
        )

        # When
        result = await service.analyze_lesson_plan(
            session_id=1,
            user_id=123
        )

        # Then
        assert result["success"] is False
        assert "error" in result
        assert "분석할 문서가 없습니다" in result["error"]

    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_timeout(
        self,
        service
    ):
        """
        타임아웃 발생 시 에러 반환
        """
        # Mock _get_criteria_context - 긴 시간 소요
        async def slow_context():
            await asyncio.sleep(200)  # 180초 초과
            return "평가기준 컨텍스트"

        service._get_criteria_context = slow_context

        # When
        result = await service.analyze_lesson_plan(
            session_id=1,
            user_id=123
        )

        # Then
        assert result["success"] is False
        assert "error" in result
        assert "시간 초과" in result["error"]
