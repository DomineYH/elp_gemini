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

    def test_post_process_strips_emojis(self, service):
        """
        Gemini가 이모지를 포함한 보고서를 반환해도 후처리 단계에서 모두 제거된다.
        """
        raw = (
            "# 📑 수업 지도안 평가 보고서\n\n"
            "## 1️⃣ 교육과정 목표 및 성격과의 부합\n\n"
            "### 📊 평가 등급: 상\n\n"
            "**💡 분석 내용**\n본문\n\n"
            "**✅ 강점**\n- 좋음\n\n"
            "**🔧 개선점**\n- 보완\n"
        )

        processed = service._post_process_report(raw)

        # 보고서 본문에 어떤 이모지도 남아 있어서는 안 된다
        for emoji_char in ["📑", "1️⃣", "📊", "💡", "✅", "🔧", "🔎", "🚀",
                           "📝", "✨", "⚡️", "📚", "🔍", "📌", "📏", "📂"]:
            assert emoji_char not in processed, (
                f"이모지 '{emoji_char}' 가 후처리 후에도 남아있음"
            )

        # 헤더 구조와 한글 본문은 보존
        assert "수업 지도안 평가 보고서" in processed
        assert "교육과정 목표 및 성격과의 부합" in processed
        assert "평가 등급: 상" in processed
        assert "강점" in processed

    def test_post_process_handles_vector_search_section_without_emoji(
        self, service
    ):
        """
        '🔍 Vector Search 참고 자료' 헤더에서 이모지가 사라져도 후처리가 정상 동작한다.
        (LLM이 이모지 없이 헤더를 출력해도 기존 가독성 개선 로직이 작동해야 한다)
        """
        raw = (
            "## 종합 평가\n\n"
            "### Vector Search 참고 자료\n"
            "이것은 100자 이상의 비구조화된 평가기준 문장입니다. "
            "두 번째 문장입니다 추가 길이를 위해. "
            "세 번째 문장입니다 더 길게 만들기 위해서요.\n\n"
            "### File Search 참고 문서\n- 문서1\n"
        )

        processed = service._post_process_report(raw)

        # 가독성 개선이 동작했다면 '- ' 로 시작하는 목록이 생성된다
        assert "- " in processed
        # 이모지는 어차피 없지만, 출력에도 없어야 한다
        assert "🔍" not in processed

    def test_post_process_preserves_emojis_in_blockquote_citations(
        self, service
    ):
        """
        수업지도안 인용 블록(>) 안의 이모지는 원본 문서의 일부이므로 보존하고,
        블록 외부의 템플릿 이모지만 제거한다.
        """
        raw = (
            "## 1. 교육과정 목표 및 성격과의 부합\n\n"
            "**근거**\n"
            "> **평가기준**: 교육과정 부합성\n"
            "> **수업지도안**: \"활동지에 ✅ 표시 후 제출\"\n\n"
            "**개선점**\n"
            "- 시간 배분 ⚡ 검토\n"
        )

        processed = service._post_process_report(raw)

        # 인용 블록 내부의 ✅ 는 원본 문서 인용이므로 반드시 보존
        assert "✅ 표시 후 제출" in processed
        # 블록 외부(개선점 본문) 의 이모지는 제거
        assert "⚡" not in processed
        # 헤더와 본문 텍스트는 보존
        assert "## 1. 교육과정 목표 및 성격과의 부합" in processed
        assert "시간 배분" in processed

    def test_post_process_preserves_nested_indentation_in_proposals(
        self, service
    ):
        """
        '구체적 제안' 섹션의 nested bullet 들여쓰기가 보존되어 마크다운
        목록 계층이 깨지지 않는다.
        """
        raw = (
            "## 5. 개선 및 보완을 위한 제안\n\n"
            "**구체적 제안**\n\n"
            "1. **[비계 설정의 구체화]**\n"
            "   - 의사코드를 사전 자료로 제공\n"
            "   - 학습 부진 학생의 중도 포기 방지\n"
        )

        processed = service._post_process_report(raw)

        # 3칸 들여쓰기가 그대로 유지되어 nested bullet 으로 렌더링 가능
        assert "   - 의사코드를 사전 자료로 제공" in processed
        assert "   - 학습 부진 학생의 중도 포기 방지" in processed

    def test_post_process_sanitizes_non_citation_blockquotes(
        self, service
    ):
        """
        '> **수업지도안**:' 가 아닌 블록 인용 라인(분석 개요, 평가기준 라벨 등)은
        살균된다. 실제 사용자 인용만 verbatim 보존.
        """
        raw = (
            "> **분석 개요**\n"
            "> - **분석 모델**: 📑gemini\n\n"
            "## 1. 교육과정 부합성\n\n"
            "**근거**\n"
            "> **평가기준**: ✅ 교육과정 부합성\n"
            "> **수업지도안**: \"활동지에 ✅ 표시 후 제출\"\n"
        )

        processed = service._post_process_report(raw)

        # 분석 개요 블록(인용 아님): 이모지 제거됨
        assert "📑" not in processed
        # 평가기준 라벨 라인(인용 아님): 이모지 제거됨
        # 해당 라인은 "> **평가기준**: 교육과정 부합성" 으로 살균되어야 함
        assert "**평가기준**: 교육과정 부합성" in processed
        # 수업지도안 인용 라인(실제 인용): 이모지 보존
        assert "활동지에 ✅ 표시 후 제출" in processed

    def test_post_process_preserves_multiline_citation_block(
        self, service
    ):
        """
        수업지도안 인용이 여러 줄에 걸쳐 있을 때, 라벨 라인 + 후속 continuation
        라인 모두 verbatim 보존되어 사용자 문서 이모지가 살아남는다.
        """
        raw = (
            "**근거**\n"
            "> **평가기준**: 부합성\n"
            "> **수업지도안**: \"활동지에\n"
            "> ✅ 표시 후\n"
            "> 🚀 제출하기\"\n\n"
            "**개선점**\n"
            "- ⚡ 검토 필요\n"
        )

        processed = service._post_process_report(raw)

        # 인용 블록의 모든 라인 보존 (✅, 🚀 모두)
        assert "✅ 표시 후" in processed
        assert "🚀 제출하기" in processed
        # 평가기준 라벨 라인은 살균 (이 라인엔 이모지 없으므로 변동 없음)
        assert "**평가기준**: 부합성" in processed
        # 인용 외부의 ⚡ 는 제거
        assert "⚡" not in processed

    def test_post_process_exits_citation_on_new_label(self, service):
        """
        수업지도안 인용 후 다른 라벨('> **개선**:' 등) 이 나오면 그 라인부터는
        살균이 다시 적용된다 (인용 모드 종료).
        """
        raw = (
            "**근거**\n"
            "> **수업지도안**: \"원본 ✅ 내용\"\n"
            "> **추가**: \"이건 인용 아님 ⚡\"\n"
        )

        processed = service._post_process_report(raw)

        # 수업지도안 라인의 ✅ 는 보존
        assert "원본 ✅ 내용" in processed
        # 새 라벨 라인의 ⚡ 는 제거 (인용 모드 종료)
        assert "⚡" not in processed

    def test_post_process_preserves_emoji_decorated_citation_label(
        self, service
    ):
        """
        모델이 인용 라벨을 이모지로 장식한 경우(예: '> **📄 수업지도안**:') 에도
        인용 모드에 진입하여 인용 본문의 사용자 이모지를 보존한다.
        """
        raw = (
            "**근거**\n"
            "> **📄 수업지도안**: \"활동지에 ✅ 표시 후 제출\"\n\n"
            "**개선점**\n"
            "- ⚡ 검토 필요\n"
        )

        processed = service._post_process_report(raw)

        # 인용 본문의 ✅ 는 보존
        assert "활동지에 ✅ 표시 후 제출" in processed
        # 외부 ⚡ 는 제거
        assert "⚡" not in processed
        # 라벨의 장식 이모지는 살균되지 않음 — 라인 전체가 verbatim 보존됨
        # (라벨 자체에서 📄 가 사라지더라도 OK; 핵심은 인용 본문 ✅ 보존)

    def test_post_process_recognizes_decorated_citation_with_continuation(
        self, service
    ):
        """
        장식된 인용 라벨 + 다중 라인 인용도 함께 작동: 라벨 장식이 있어도
        continuation 라인까지 verbatim 보존된다.
        """
        raw = (
            "> **📄 수업지도안**: \"활동지에\n"
            "> ✅ 표시\n"
            "> 후 제출\"\n\n"
            "**개선점**\n"
            "- ⚡ 검토\n"
        )

        processed = service._post_process_report(raw)

        # 인용 블록의 모든 라인 verbatim 보존
        assert "✅ 표시" in processed
        # 외부 ⚡ 제거
        assert "⚡" not in processed

    def test_post_process_recognizes_spaced_citation_label(self, service):
        """
        '수업 지도안' (띄어쓴 형태) 라벨도 인용으로 인식한다 — prompt/UI 에서
        실제로 사용되는 자연스러운 표기.
        """
        raw = (
            "**근거**\n"
            "> **수업 지도안**: \"활동지에 ✅ 표시 후 제출\"\n\n"
            "**개선점**\n"
            "- ⚡ 검토 필요\n"
        )

        processed = service._post_process_report(raw)

        # 띄어쓴 라벨의 인용 본문도 ✅ 보존
        assert "활동지에 ✅ 표시 후 제출" in processed
        # 외부 ⚡ 제거
        assert "⚡" not in processed

    def test_post_process_recognizes_decorated_spaced_citation_label(
        self, service
    ):
        """
        장식 + 띄어쓰기 결합('> **📄 수업 지도안**:') 도 인용으로 인식.
        """
        raw = (
            "> **📄 수업 지도안**: \"문서 본문 ✅\"\n\n"
            "- ⚡ 외부\n"
        )

        processed = service._post_process_report(raw)

        assert "문서 본문 ✅" in processed
        assert "⚡" not in processed

    def test_post_process_keeps_bold_lines_inside_citation_block(
        self, service
    ):
        """
        다중 라인 인용 본문 안에 굵은 텍스트(`> **준비물**`) 가 있어도 인용 모드를
        종료하지 않고 verbatim 보존한다. 새 라벨은 콜론 형태(`> **라벨**:`) 로만 인식.
        """
        raw = (
            "**근거**\n"
            "> **수업지도안**: \"활동 흐름은 다음과 같다\n"
            "> **준비물** ✅: 색종이, 풀, 활동지\n"
            "> **유의사항** 🚀: 모둠별 협력\"\n\n"
            "**개선점**\n"
            "- ⚡ 외부\n"
        )

        processed = service._post_process_report(raw)

        # 인용 본문의 굵은 라인들도 verbatim 보존 (✅, 🚀 모두)
        assert "**준비물** ✅" in processed
        assert "**유의사항** 🚀" in processed
        # 외부 ⚡ 는 제거
        assert "⚡" not in processed

    def test_post_process_exits_citation_only_on_label_with_colon(
        self, service
    ):
        """
        인용 모드는 콜론 형태의 새 라벨('> **<라벨>**:') 을 만났을 때만 종료된다.
        콜론 없는 굵은 블록인용은 continuation 으로 간주.
        """
        raw = (
            "> **수업지도안**: \"본문 1\n"
            "> **소제목**\n"
            "> 본문 2 ✅\"\n"
            "> **다음 라벨**: 새 콘텐츠 ⚡\n"
        )

        processed = service._post_process_report(raw)

        # 인용 안의 굵은 줄 + 본문 보존
        assert "**소제목**" in processed
        assert "본문 2 ✅" in processed
        # 콜론 형태의 새 라벨 라인부터는 살균
        assert "⚡" not in processed

    def test_post_process_normalizes_multiline_bold_label_after_emoji(
        self, service
    ):
        """
        모델이 굵은 라벨을 여러 줄에 걸쳐 출력해도, 이모지 제거 후 잔여 공백이
        흡수되어 strong-emphasis 가 유지된다.
        """
        raw = (
            "**🚀 분석\n"
            "내용**\n\n"
            "본문 텍스트\n"
        )

        processed = service._post_process_report(raw)

        # 멀티라인 굵은 영역의 잔여 공백 정리: '** 분석\n내용**' → '**분석\n내용**'
        # (이모지 제거 후 strip 이 양 끝에 적용됨)
        assert "**분석\n내용**" in processed
        # 잘못된 단독 opener('** 분석') 부재
        assert "** 분석" not in processed

    def test_post_process_normalizes_multiline_bold_at_end(
        self, service
    ):
        """
        굵은 영역의 닫는 마커가 다음 줄에 나오는 경우도 정상 처리.
        """
        raw = (
            "**foo\n"
            "bar ✅**\n"
        )

        processed = service._post_process_report(raw)

        # 닫는 마커 앞 잔여 공백 흡수: '**foo\nbar **' → '**foo\nbar**'
        assert "**foo\nbar**" in processed
        assert "bar **" not in processed

    def test_post_process_preserves_citation_emojis_with_buffered_sanitization(
        self, service
    ):
        """
        버퍼링 변경 후에도 인용 블록의 이모지는 그대로 보존된다 (회귀 가드).
        """
        raw = (
            "**근거**\n"
            "> **수업 지도안**: \"활동지에 ✅ 표시\"\n\n"
            "**개선점**\n"
            "- ⚡ 검토\n"
        )

        processed = service._post_process_report(raw)

        assert "✅ 표시" in processed
        assert "⚡" not in processed
        assert "**근거**" in processed
        assert "**개선점**" in processed
