"""
LessonPlanAnalysisService 테스트
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from google.genai import types

from app.services.lessonplan_analysis_service import (
    LessonPlanAnalysisService,
    _finish_reason_name,
    _report_problems,
)


def _reach_store_lookup(service):
    """중복 분석·업로드 확인을 통과시켜 _get_store_ids 단계까지 보낸다."""
    service._find_existing_report_for_latest_upload = AsyncMock(
        return_value=(None, None)
    )
    service.lessonplan_storage.list_lessonplans = Mock(
        return_value=[{"filename": "plan.pdf"}]
    )
    service._user_file_search_store_has_documents = Mock(return_value=False)


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
        # name=은 Mock 자신의 이름이라 .name 속성은 따로 지정한다
        rubric = MagicMock(display_name="rubricstore")
        rubric.name = "fileSearchStores/rubric123"
        user_store = MagicMock(display_name="user-123-store")
        user_store.name = "fileSearchStores/user123"
        service.file_search_service.client.file_search_stores.list = MagicMock(
            return_value=[rubric, user_store]
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
            MagicMock(
                display_name="other-store", name="fileSearchStores/other"
            ),
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
        result = service._build_analysis_prompt(system_prompt)

        # Then: 스토어 이름 대신 역할 이름만 (#174)
        assert system_prompt in result
        assert "평가기준 문서" in result
        assert "수업 지도안" in result
        assert "fileSearchStores/" not in result
        assert "rubricstore" not in result
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
        assert (
            result["grounding_chunks"][0]["uri"]
            == "fileSearchStores/xxx/documents/yyy"
        )

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

        _reach_store_lookup(service)
        service._get_store_ids = AsyncMock(return_value=[])

        # When
        result = await service.analyze_lesson_plan(session_id, user_id)

        # Then
        service._get_store_ids.assert_awaited_once_with(user_id)
        assert result["success"] is False
        assert "분석할 문서가 없습니다" in result["error"]

    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_timeout(self, service, monkeypatch):
        """타임아웃 에러 처리"""
        # Given
        session_id = 1
        user_id = 123

        # 180초를 실제로 기다리지 않도록 타임아웃만 줄인다
        real_timeout = asyncio.timeout
        monkeypatch.setattr(asyncio, "timeout", lambda _s: real_timeout(0.05))

        async def slow_store_ids(*args, **kwargs):
            await asyncio.sleep(1)
            return []

        _reach_store_lookup(service)
        service._get_store_ids = slow_store_ids

        # When
        result = await service.analyze_lesson_plan(session_id, user_id)

        # Then
        assert result["success"] is False
        assert "시간 초과" in result["error"]


# #439: 저장 전 검사를 통과하는 1~5절 제목 본문
VALID_SECTIONS = "".join(f"## {n}. 절\n\n본문\n\n" for n in range(1, 6))


@pytest.mark.parametrize(
    "text, finish_reason, expected",
    [
        (VALID_SECTIONS, "STOP", []),
        (VALID_SECTIONS, None, []),
        ("# 3. 절\n#1 절\n###  2\n## 4 절\n# 5", None, []),
        ("# 보고서\n\n## 1. 절\n\n본문", "STOP", ["절 없음: 2,3,4,5"]),
        ("", None, ["절 없음: 1,2,3,4,5"]),
        (
            "## 10. 절\n" + VALID_SECTIONS.replace("## 1. 절", "본문"),
            "STOP",
            ["절 없음: 1"],
        ),
        (
            VALID_SECTIONS.replace("## 1. 절", "#### 1. 절"),
            None,
            ["절 없음: 1"],
        ),
        (VALID_SECTIONS, "MAX_TOKENS", ["finish_reason=MAX_TOKENS"]),
        (VALID_SECTIONS + "도입 단계에서" + "거" * 29, "STOP", []),
        (VALID_SECTIONS + "도입 단계에서" + "거" * 30, "STOP", ["반복"]),
        (VALID_SECTIONS + "학습 목표를 " * 9, "STOP", []),
        (VALID_SECTIONS + "학습 목표를 " * 10, "STOP", ["반복"]),
        (
            VALID_SECTIONS
            + "---\n\n| a | b |\n|---|---|\n\n"
            + "-" * 40
            + "\n"
            + "|---" * 12
            + "|\n"
            + "=" * 40,
            "STOP",
            [],
        ),
        (
            "## 1\n" + "거" * 30,
            "MAX_TOKENS",
            ["finish_reason=MAX_TOKENS", "절 없음: 2,3,4,5", "반복"],
        ),
    ],
    ids=[
        "1-5절 정상",
        "finish_reason 미상",
        "제목 모양 변형",
        "2-5절 없음",
        "빈 본문",
        "10절은 1절이 아님",
        "h4 는 제목 아님",
        "MAX_TOKENS",
        "같은 글자 29회",
        "같은 글자 30회",
        "구절 9회",
        "구절 10회",
        "구분선·표·대시 40개",
        "사유 여러 개",
    ],
)
def test_report_problems(text, finish_reason, expected):
    assert _report_problems(text, finish_reason) == expected


@pytest.mark.parametrize(
    "candidates, expected",
    [
        ([], None),
        (None, None),
        ([SimpleNamespace()], None),
        ([SimpleNamespace(finish_reason=None)], None),
        ([MagicMock()], None),
        ([SimpleNamespace(finish_reason="MAX_TOKENS")], "MAX_TOKENS"),
        ([SimpleNamespace(finish_reason=types.FinishReason.STOP)], "STOP"),
        (
            [SimpleNamespace(finish_reason=types.FinishReason.MAX_TOKENS)],
            "MAX_TOKENS",
        ),
    ],
    ids=[
        "후보 없음",
        "후보 None",
        "속성 없음",
        "값 None",
        "Mock",
        "문자열",
        "enum STOP",
        "enum MAX_TOKENS",
    ],
)
def test_finish_reason_name(candidates, expected):
    assert (
        _finish_reason_name(SimpleNamespace(candidates=candidates)) == expected
    )


@pytest.mark.parametrize(
    "given, expected",
    [
        (
            "**개선점 (현재 → 수정 제안)\n\n본문",
            "**개선점 (현재 → 수정 제안)**\n\n본문",
        ),
        (
            "**구체적 제안 (현재 → 수정 제안)\n1. **제목**: 내용",
            "**구체적 제안 (현재 → 수정 제안)**\n1. **제목**: 내용",
        ),
        ("   **수정 근거\n", "   **수정 근거**\n"),
        (
            "**📌 개선점 (현재 → 수정 제안)\n\n본문",
            "**개선점 (현재 → 수정 제안)**\n\n본문",
        ),
        (
            "**개선점\n본문 **굵게** 끝\n\n**다음 라벨\n- **항목**: 내용",
            "**개선점**\n본문 **굵게** 끝\n\n**다음 라벨**\n- **항목**: 내용",
        ),
        ("**강점**\n- **항목**: 내용\n1. **제목**", None),
        ("**foo\nbar** 뒤", None),
        ('> **수업지도안**: "**강조 없는 원문"', None),
        ("내용 **강조 없이 끝", None),
        ('- 현재 지도안: "| 1 | 도입 | 관찰 | 상 |"', None),
    ],
    ids=[
        "빈 줄 앞 라벨",
        "번호 목록 앞 라벨",
        "들여쓴 라벨",
        "이모지 라벨",
        "문단당 첫 라벨만",
        "닫힌 라벨·목록",
        "여러 줄 굵게",
        "인용 블록",
        "문장 중간",
        "파이프 인용",
    ],
)
def test_post_process_closes_dangling_bold_label(service, given, expected):
    """#441: 닫히지 않은 단독 굵은 라벨만 닫고 나머지는 그대로 둔다"""
    processed = service._post_process_report(given)
    assert processed == (given if expected is None else expected)
