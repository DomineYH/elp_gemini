"""
CriteriaContextService 단위 테스트
CriteriaVectorService 검색 결과를 QnA 컨텍스트로 가공하는 기능 검증
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services.criteria_context_service import (
    CriteriaContextService,
)

EMPTY_CONTEXT = {
    "context_text": "",
    "criteria_ids": [],
    "criteria_metadata": [],
    "citations": [],
}


@pytest.fixture
def mock_vector_cls():
    with patch(
        "app.services.criteria_context_service.CriteriaVectorService"
    ) as cls:
        yield cls


class TestCriteriaContextService:
    """CriteriaContextService 테스트"""

    def test_init_success(self, mock_vector_cls):
        """검색을 CriteriaVectorService에 위임하고 db를 보관한다"""
        db = Mock()

        service = CriteriaContextService(db=db)

        assert service.vector_service is mock_vector_cls.return_value
        assert service.db is db

    async def test_get_context_success(self, mock_vector_cls):
        """검색 결과를 포맷하고 citation 제목으로 평가기준 ID를 찾는다"""
        citations = [{"title": "평가기준 A"}]
        search = AsyncMock(
            return_value={
                "response_text": (
                    "수업 목표가 성취기준과 명확히 연결되어야 합니다. "
                    "두 번째 문장도 충분히 길게 작성되어 있습니다."
                ),
                "citations": citations,
            }
        )
        mock_vector_cls.return_value.search_criteria = search
        criteria = Mock(
            id=1, display_alias=None, title="평가기준 A", file_path="x"
        )
        db = Mock()
        db.execute = AsyncMock(
            return_value=Mock(scalar_one_or_none=Mock(return_value=criteria))
        )

        result = await CriteriaContextService(db=db).get_context("질문")

        search.assert_awaited_once_with(query="질문", temperature=0.3)
        assert result["criteria_ids"] == [1]
        assert result["criteria_metadata"] == [
            {"id": 1, "title": "평가기준 A", "file_path": "x"}
        ]
        assert result["context_text"].startswith("**주요 평가 관점:**")
        assert result["citations"] == citations

    async def test_get_context_no_active(self, mock_vector_cls):
        """검색 결과 텍스트가 없으면 빈 컨텍스트"""
        mock_vector_cls.return_value.search_criteria = AsyncMock(
            return_value={"response_text": "", "citations": []}
        )

        result = await CriteriaContextService().get_context("질문")

        assert result == EMPTY_CONTEXT

    async def test_get_context_api_error(self, mock_vector_cls):
        """검색 실패는 삼키고 빈 컨텍스트를 돌려준다 (QnA는 계속 진행)"""
        mock_vector_cls.return_value.search_criteria = AsyncMock(
            side_effect=RuntimeError("API Error")
        )

        result = await CriteriaContextService().get_context("질문")

        assert result == EMPTY_CONTEXT

    def test_format_context_as_markdown(self, mock_vector_cls):
        """짧은 문장은 버리고 번호 목록과 중복 없는 출처를 만든다"""
        service = CriteriaContextService()
        text = "짧음. 수업 목표가 성취기준과 명확히 연결되어야 합니다"

        formatted = service.format_context_as_markdown(
            text, [{"title": "A"}, {"title": "A"}]
        )

        assert formatted == (
            "**주요 평가 관점:**\n"
            "1. 수업 목표가 성취기준과 명확히 연결되어야 합니다.\n"
            "\n**출처 문서:**\n"
            "- A"
        )
        assert service.format_context_as_markdown("", []) == ""
