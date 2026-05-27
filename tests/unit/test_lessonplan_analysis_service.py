"""
LessonPlanAnalysisService 단위 테스트
Phase 3에서 구현된 수업 지도안 분석 기능 검증
"""
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services.lessonplan_analysis_service import LessonPlanAnalysisService


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
        assert "교육과정 목표" in result
        assert "내용 체계" in result
        assert "교수·학습 방법" in result
        assert "평가 방향" in result
        assert "개선 및 보완" in result

    def test_build_analysis_prompt_omits_model_name(self, service):
        """프롬프트에서 모델 이름이 더 이상 치환/포함되지 않는다."""
        # Given: 템플릿에 {model_name} 플레이스홀더가 그대로 남아 있는
        #         경우에도 치환되지 않고, 동시에 빌더가 self.model_name 을
        #         본문에 끼워넣지도 않아야 한다.
        system_prompt = (
            "수업 지도안 평가 시스템 프롬프트\n"
            "분석 모델: {model_name}"
        )

        # When
        result = service._build_analysis_prompt(
            system_prompt,
            rubric_store_id="rubric-store",
            lesson_store_id="lesson-store",
        )

        # Then: 실제 모델 식별자(self.model_name)는 본문에 등장하지 않는다
        assert service.model_name not in result
        # 그리고 {model_name} 플레이스홀더도 치환되지 않은 채 그대로다
        #  (이 줄은 prompt.md 에서 삭제되었지만, 빌더 단위로는 input string 의
        #   해당 토큰을 더 이상 치환하지 않음을 보장하기 위한 검사)
        assert "{model_name}" in result

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
        # Mock _get_store_ids - 긴 시간 소요
        async def slow_store_ids(*args, **kwargs):
            await asyncio.sleep(200)  # 180초 초과
            return []

        service._get_store_ids = slow_store_ids

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
        Gemini가 이모지를 포함한 보고서를 반환해도 후처리 단계에서
        모두 제거된다.
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

    def test_post_process_strips_stray_model_line(self, service):
        """LLM 이 학습된 양식으로 `**분석 모델**:` 줄을 출력해도
        후처리가 제거한다."""
        raw = (
            "# 수업 지도안 평가 보고서\n\n"
            "> **분석 개요**\n"
            "> - **분석 일시**: 2026-05-27 12:34\n"
            "> - **분석 모델**: gemini-2.5-flash\n"
            "\n"
            "## 1. 교육과정 목표 및 성격과의 부합\n"
            "본문\n"
        )

        processed = service._post_process_report(raw)

        # 모델명 줄이 제거된다
        assert "**분석 모델**" not in processed
        assert "gemini-2.5-flash" not in processed
        # 인접한 다른 헤더 라인은 보존
        assert "**분석 개요**" in processed
        assert "**분석 일시**" in processed
        assert "2026-05-27 12:34" in processed
        assert "## 1. 교육과정 목표 및 성격과의 부합" in processed

    def test_post_process_handles_vector_search_section_without_emoji(
        self, service
    ):
        """
        '🔍 Vector Search 참고 자료' 헤더에서 이모지가 사라져도 후처리가
        정상 동작한다.
        (LLM이 이모지 없이 헤더를 출력해도 기존 가독성 개선 로직이
        작동해야 한다)
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
        '> **수업지도안**:' 가 아닌 블록 인용 라인(분석 개요, 평가기준
        라벨 등)은 살균된다. 실제 사용자 인용만 verbatim 보존.
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
        다중 라인 인용 본문 안에 굵은 텍스트(`> **준비물**`) 가 있어도
        인용 모드를 종료하지 않고 verbatim 보존한다. 새 라벨은 콜론
        형태(`> **라벨**:`) 로만 인식.
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
        인용 모드는 콜론 형태의 새 라벨('> **<라벨>**:') 을 만났을
        때만 종료된다. 콜론 없는 굵은 블록인용은 continuation 으로
        간주.
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

        # 멀티라인 굵은 영역의 잔여 공백 정리:
        # '** 분석\n내용**' → '**분석\n내용**'
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

    def test_post_process_does_not_let_unclosed_bold_consume_next_header(
        self, service
    ):
        """
        모델이 굵은 마커를 닫지 않은 채 다음 섹션으로 넘어가면, 빈 줄(단락 경계)
        에서 살균을 분리하여 다음 섹션 헤더를 침범하지 않게 한다.
        """
        raw = (
            "**강점\n"
            "\n"
            "**개선점**\n"
        )

        processed = service._post_process_report(raw)

        # 다음 단락의 굵은 헤더가 보존되어야 함
        assert "**개선점**" in processed
        # 단락 경계(빈 줄) 가 보존되어야 함
        assert "\n\n" in processed
        # 닫히지 않은 첫 줄이 다음 섹션과 합쳐지면 안 됨
        assert "**강점**개선점**" not in processed

    def test_post_process_does_not_collapse_blank_line_between_sections(
        self, service
    ):
        """
        섹션 간 빈 줄이 살균 과정에서 사라지지 않는다 (단락 경계 보존).
        """
        raw = (
            "**🚀 첫 섹션**\n"
            "\n"
            "**✅ 두 번째 섹션**\n"
        )

        processed = service._post_process_report(raw)

        # 두 굵은 라벨 모두 정상 유지
        assert "**첫 섹션**" in processed
        assert "**두 번째 섹션**" in processed
        # 빈 줄 보존
        assert "\n\n" in processed

    def test_post_process_replaces_file_search_section(self, service):
        """LLM 이 생성한 `### File Search 참고 문서` 본문이 서버
        렌더로 교체된다."""
        raw = (
            "## 종합 평가\n\n"
            "요약 본문\n\n"
            "### File Search 참고 문서\n"
            "- LLM 이 적은 임의의 문서 제목\n"
            "- 또 다른 임의 항목\n"
        )

        processed = service._post_process_report(
            raw,
            criteria_aliases=["정보 교육과정 평가기준"],
            lessonplan_original_filename="수업안.pdf",
        )

        # 서버 렌더 항목이 등장한다
        assert "- 정보 교육과정 평가기준" in processed
        assert "- 수업안.pdf" in processed
        # LLM 이 적은 임의 항목은 사라진다
        assert "LLM 이 적은 임의의 문서 제목" not in processed
        assert "또 다른 임의 항목" not in processed
        # 헤더는 보존된다
        assert "### File Search 참고 문서" in processed
        # 이전 섹션도 보존
        assert "## 종합 평가" in processed
        assert "요약 본문" in processed

    def test_post_process_appends_file_search_section_when_missing(
        self, service
    ):
        """보고서에 섹션이 없으면 끝에 부착한다."""
        raw = (
            "## 종합 평가\n\n"
            "요약 본문\n"
        )

        processed = service._post_process_report(
            raw,
            criteria_aliases=["A 기준"],
            lessonplan_original_filename="lesson.pdf",
        )

        assert "### File Search 참고 문서" in processed
        assert "- A 기준" in processed
        assert "- lesson.pdf" in processed
        # 부착되어도 이전 본문은 보존
        assert "## 종합 평가" in processed

    def test_post_process_keeps_legacy_signature(self, service):
        """기존 호출 형태(인자 미제공)는 그대로 작동하여 회귀가 없다."""
        raw = (
            "## 종합 평가\n\n"
            "요약 본문\n\n"
            "### File Search 참고 문서\n"
            "- LLM 이 적은 임의 항목\n"
        )

        processed = service._post_process_report(raw)

        # 인자가 없으면 섹션 치환 단계가 건너뛰어진다 → LLM 출력 유지
        assert "LLM 이 적은 임의 항목" in processed

    @pytest.mark.asyncio
    async def test_collect_active_criteria_display_names_sorted(
        self, service
    ):
        """active 항목들의 alias 가 activated_at desc, stable_id desc
        로 정렬되어 반환된다."""
        from app.schemas.alias_map import AliasMap, AliasMapEntry

        alias_map = AliasMap(
            schema_version=1,
            updated_at="2026-05-27T00:00:00Z",
            entries={
                "01OLDER": AliasMapEntry(
                    alias="구버전 기준",
                    status="active",
                    activated_at="2026-05-20T00:00:00Z",
                ),
                "01NEWER": AliasMapEntry(
                    alias="최신 기준",
                    status="active",
                    activated_at="2026-05-25T00:00:00Z",
                ),
                "01INACTIVE": AliasMapEntry(
                    alias="비활성",
                    status="uploaded",
                    activated_at=None,
                ),
            },
        )

        with patch(
            "app.services.criteria_alias_map_service"
            ".CriteriaAliasMapService.fetch",
            new=AsyncMock(return_value=("doc/name", alias_map)),
        ):
            names = await service._collect_active_criteria_display_names()

        assert names == ["최신 기준", "구버전 기준"]

    @pytest.mark.asyncio
    async def test_collect_active_criteria_display_names_skips_missing_alias(
        self, service, caplog
    ):
        """alias 가 None/빈 문자열인 active 항목은 결과에서 제외되고
        경고 로그가 남는다."""
        from app.schemas.alias_map import AliasMap, AliasMapEntry

        alias_map = AliasMap(
            schema_version=1,
            updated_at="2026-05-27T00:00:00Z",
            entries={
                "01ALIASNONE": AliasMapEntry(
                    alias=None,
                    status="active",
                    activated_at="2026-05-25T00:00:00Z",
                ),
                "01EMPTY": AliasMapEntry(
                    alias="",
                    status="active",
                    activated_at="2026-05-24T00:00:00Z",
                ),
                "01OK": AliasMapEntry(
                    alias="정상 alias",
                    status="active",
                    activated_at="2026-05-23T00:00:00Z",
                ),
            },
        )

        with patch(
            "app.services.criteria_alias_map_service"
            ".CriteriaAliasMapService.fetch",
            new=AsyncMock(return_value=("doc/name", alias_map)),
        ):
            with caplog.at_level("WARNING"):
                names = await service._collect_active_criteria_display_names()

        assert names == ["정상 alias"]
        assert any(
            "alias 누락" in record.message
            or "alias missing" in record.message.lower()
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_collect_active_criteria_display_names_fetch_failure(
        self, service
    ):
        """fetch 가 예외를 던지면 빈 리스트를 반환하고 예외를
        전파하지 않는다."""
        with patch(
            "app.services.criteria_alias_map_service"
            ".CriteriaAliasMapService.fetch",
            new=AsyncMock(side_effect=RuntimeError("network down")),
        ):
            names = await service._collect_active_criteria_display_names()

        assert names == []

    def test_render_file_search_references_full(self, service):
        """평가기준 alias + 수업지도안 파일명이 모두 있으면 항목 3개를
        반환한다."""
        rendered = service._render_file_search_references_section(
            criteria_aliases=["A 기준", "B 기준"],
            lessonplan_original_filename="우리반 수업계획.pdf",
        )
        assert rendered == (
            "- A 기준\n"
            "- B 기준\n"
            "- 우리반 수업계획.pdf"
        )

    def test_render_file_search_references_only_criteria(self, service):
        """수업지도안 파일명이 없으면 평가기준만 표시한다."""
        rendered = service._render_file_search_references_section(
            criteria_aliases=["A 기준"],
            lessonplan_original_filename=None,
        )
        assert rendered == "- A 기준"

    def test_render_file_search_references_only_lessonplan(self, service):
        """평가기준 alias 가 비어도 수업지도안 파일명만 표시한다."""
        rendered = service._render_file_search_references_section(
            criteria_aliases=[],
            lessonplan_original_filename="lesson.pdf",
        )
        assert rendered == "- lesson.pdf"

    def test_render_file_search_references_empty(self, service):
        """둘 다 비면 placeholder 를 반환한다."""
        rendered = service._render_file_search_references_section(
            criteria_aliases=[],
            lessonplan_original_filename=None,
        )
        assert rendered == "(표시할 항목이 없습니다)"

    def test_resolve_lessonplan_original_filename_from_upload(self, service):
        """latest_upload 가 있으면 그것의 original_filename 을 반환한다."""
        upload = Mock()
        upload.original_filename = "수업안.pdf"
        result = service._resolve_lessonplan_original_filename(
            latest_upload=upload,
            legacy_lessonplans=[],
        )
        assert result == "수업안.pdf"

    def test_resolve_lessonplan_original_filename_from_legacy(self, service):
        """latest_upload 가 None 이면 legacy 목록 중 최신 항목 사용."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        legacy = [
            {
                "original_filename": "old.pdf",
                "filename": "x_old.pdf",
                "created_at": now - timedelta(days=1),
            },
            {
                "original_filename": "new.pdf",
                "filename": "x_new.pdf",
                "created_at": now,
            },
        ]
        result = service._resolve_lessonplan_original_filename(
            latest_upload=None,
            legacy_lessonplans=legacy,
        )
        assert result == "new.pdf"

    def test_resolve_lessonplan_original_filename_none(self, service):
        """둘 다 없으면 None 반환."""
        result = service._resolve_lessonplan_original_filename(
            latest_upload=None,
            legacy_lessonplans=[],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_writes_server_rendered_refs(
        self, service
    ):
        """분석 결과 보고서에 서버 렌더 참고 문서 섹션이 포함되고
        모델명은 노출되지 않는다."""
        from app.schemas.alias_map import AliasMap, AliasMapEntry

        service._get_store_ids = AsyncMock(
            return_value=["user-store", "rubric-store"]
        )
        service.prompt_loader.get_prompt = Mock(
            return_value="lesson_analysis prompt"
        )

        # active criteria filter & alias_map fetch
        with patch(
            "app.services.criteria_vector_service"
            ".CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="X"'),
        ), patch(
            "app.services.criteria_alias_map_service"
            ".CriteriaAliasMapService.fetch",
            new=AsyncMock(
                return_value=(
                    "doc/name",
                    AliasMap(
                        schema_version=1,
                        updated_at="2026-05-27T00:00:00Z",
                        entries={
                            "01OK": AliasMapEntry(
                                alias="정보 교육과정 평가기준",
                                status="active",
                                activated_at="2026-05-25T00:00:00Z",
                            ),
                        },
                    ),
                )
            ),
        ):
            # Gemini 응답에 모델명 라인과 임의 참고문서 섹션 포함
            mock_response = Mock()
            mock_response.text = (
                "# 보고서\n\n"
                "> **분석 모델**: secret-internal-model\n\n"
                "## 종합 평가\n본문\n\n"
                "### File Search 참고 문서\n- 임의 항목\n"
            )
            mock_response.candidates = []
            service.client.models.generate_content = Mock(
                return_value=mock_response
            )

            # legacy 경로 사용 — DB 의존 분기 회피
            service._find_existing_report_for_latest_upload = AsyncMock(
                return_value=(None, None)
            )
            service._user_file_search_store_has_documents = Mock(
                return_value=True
            )
            service.lessonplan_storage.list_lessonplans = Mock(
                return_value=[]
            )
            # 보고서 저장 모킹 — 파일 시스템 회피
            service.report_storage.save_report = Mock(
                return_value={
                    "filename": "report.md",
                    "file_path": "/tmp/report.md",
                }
            )

            result = await service.analyze_lesson_plan(
                session_id=1,
                user_id=123,
                username="alice",
            )

        assert result["success"] is True
        report = result["report"]
        assert "정보 교육과정 평가기준" in report
        assert "secret-internal-model" not in report
        assert "**분석 모델**" not in report
        assert "임의 항목" not in report
