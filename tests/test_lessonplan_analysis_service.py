"""
LessonPlanAnalysisService 테스트
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.lessonplan_analysis_service import LessonPlanAnalysisService


@pytest.fixture
def mock_db():
    """Mock DB 세션"""
    return AsyncMock()


@pytest.fixture
def service(mock_db):
    """LessonPlanAnalysisService 인스턴스"""
    return LessonPlanAnalysisService(db=mock_db)


class TestLessonPlanAnalysisService:
    """LessonPlanAnalysisService 단위 테스트"""

    @pytest.mark.asyncio
    async def test_get_store_ids_success(self, service):
        """Store ID 조회 성공"""
        # Given
        user_id = 123
        mock_stores = [
            MagicMock(display_name="rubricstore", name="fileSearchStores/rubric123"),
            MagicMock(display_name="user-123-store", name="fileSearchStores/user123"),
        ]
        service.file_search_service.client.file_search_stores.list = MagicMock(
            return_value=mock_stores
        )

        # When
        result = await service._get_store_ids(user_id)

        # Then
        assert len(result) == 2
        assert "fileSearchStores/rubric123" in result
        assert "fileSearchStores/user123" in result

    @pytest.mark.asyncio
    async def test_get_store_ids_not_found(self, service):
        """Store 없을 시 빈 리스트 반환"""
        # Given
        user_id = 999
        mock_stores = [
            MagicMock(display_name="other-store", name="fileSearchStores/other"),
        ]
        service.file_search_service.client.file_search_stores.list = MagicMock(
            return_value=mock_stores
        )

        # When
        result = await service._get_store_ids(user_id)

        # Then
        assert result == []

    def test_build_analysis_prompt(self, service):
        """프롬프트 구성 테스트"""
        # Given
        system_prompt = "당신은 평가 전문가입니다."

        # When
        result = service._build_analysis_prompt(
            system_prompt,
            rubric_store_id="rubric-store",
            lesson_store_id="lesson-store",
        )

        # Then
        assert system_prompt in result
        assert "rubric-store" in result
        assert "lesson-store" in result
        assert "5개 항목" in result

    def test_extract_citations_success(self, service):
        """Citation 추출 성공"""
        # Given
        mock_response = MagicMock()
        mock_candidate = MagicMock()
        mock_grounding = MagicMock()
        mock_chunk = MagicMock()
        mock_retrieved_context = MagicMock()

        mock_retrieved_context.uri = "fileSearchStores/xxx/documents/yyy"
        mock_retrieved_context.title = "평가기준 문서"
        mock_chunk.retrieved_context = mock_retrieved_context
        mock_grounding.grounding_chunks = [mock_chunk]
        mock_candidate.grounding_metadata = mock_grounding
        mock_response.candidates = [mock_candidate]

        # When
        result = service._extract_citations(mock_response)

        # Then
        assert result is not None
        assert len(result["grounding_chunks"]) == 1
        assert result["grounding_chunks"][0]["source"] == "file_search"
        assert result["grounding_chunks"][0]["uri"] == "fileSearchStores/xxx/documents/yyy"

    def test_extract_citations_no_grounding(self, service):
        """Citation 없을 시 빈 딕셔너리 반환"""
        # Given
        mock_response = MagicMock()
        mock_response.candidates = []

        # When
        result = service._extract_citations(mock_response)

        # Then
        assert result["grounding_chunks"] == []

    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_no_stores(self, service):
        """Store 없을 시 에러 반환"""
        # Given
        session_id = 1
        user_id = 999

        service._get_store_ids = AsyncMock(return_value=[])

        # When
        result = await service.analyze_lesson_plan(session_id, user_id)

        # Then
        assert result["success"] is False
        assert "분석할 문서가 없습니다" in result["error"]

    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_timeout(self, service):
        """타임아웃 에러 처리"""
        # Given
        session_id = 1
        user_id = 123

        import asyncio
        async def slow_store_ids(*args, **kwargs):
            await asyncio.sleep(200)  # 180초 초과
            return []

        service._get_store_ids = slow_store_ids

        # When
        result = await service.analyze_lesson_plan(session_id, user_id)

        # Then
        assert result["success"] is False
        assert "시간 초과" in result["error"]
