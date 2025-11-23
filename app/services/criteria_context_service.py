"""
평가 기준 컨텍스트 서비스
QnA 시 평가 기준을 검색하여 컨텍스트로 제공
"""
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.criteria_vector_service import CriteriaVectorService
from app.models.criteria import Criteria

logger = logging.getLogger(__name__)


class CriteriaContextService:
    """평가 기준 컨텍스트 서비스"""

    def __init__(self, db: Optional[AsyncSession] = None):
        self.vector_service = CriteriaVectorService()
        self.db = db

    def format_context_as_markdown(
        self, context_text: str, citations: List[Dict[str, Any]]
    ) -> str:
        """
        Vector Search 결과를 구조화된 Markdown 형식으로 변환

        Args:
            context_text: Gemini가 반환한 원문
            citations: 출처 정보

        Returns:
            구조화된 Markdown 텍스트
        """
        if not context_text:
            return ""

        # 1. 문장 단위로 분리 (마침표 기준)
        # 여러 줄의 텍스트를 하나로 합치고 문장으로 분리
        clean_text = context_text.replace('\n', ' ').strip()

        # 마침표로 문장 분리 (단, 소수점이나 약어는 제외)
        import re
        sentences = re.split(r'(?<=[.!?])\s+', clean_text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]  # 너무 짧은 문장 제외

        # 2. 주요 평가 관점 추출 (처음 5개 문장을 관점으로 간주)
        formatted_lines = ["**주요 평가 관점:**"]

        for i, sentence in enumerate(sentences[:5], 1):
            # 각 문장을 번호 매기기
            if not sentence.endswith(('.', '!', '?')):
                sentence += '.'
            formatted_lines.append(f"{i}. {sentence}")

        # 나머지 문장들은 적용 기준으로 분류
        if len(sentences) > 5:
            formatted_lines.append("\n**적용 기준:**")
            for sentence in sentences[5:10]:  # 최대 5개의 추가 문장
                if not sentence.endswith(('.', '!', '?')):
                    sentence += '.'
                formatted_lines.append(f"- {sentence}")

        # 3. 출처 정보 추가
        if citations:
            formatted_lines.append("\n**출처 문서:**")
            seen_titles = set()
            for citation in citations:
                title = citation.get('title', '제목 없음')
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    formatted_lines.append(f"- {title}")

        return '\n'.join(formatted_lines)

    async def get_context(
        self, question: str
    ) -> Dict[str, Any]:
        """
        질문과 관련된 평가 기준 컨텍스트 검색

        Args:
            question: 사용자 질문

        Returns:
            {
                "context_text": str,  # 기존 텍스트
                "criteria_ids": List[int],  # 사용된 평가기준 ID
                "criteria_metadata": List[Dict],  # 평가기준 메타데이터
                "citations": List[Dict]  # 원본 citations
            }
        """
        try:
            # 평가 기준 검색
            result = await self.vector_service.search_criteria(
                query=question,
                temperature=0.3  # 정확도 중시
            )

            response_text = result.get("response_text", "")
            citations = result.get("citations", [])

            if not response_text:
                return {
                    "context_text": "",
                    "criteria_ids": [],
                    "criteria_metadata": [],
                    "citations": []
                }

            # Citations에서 평가기준 정보 추출
            criteria_ids = []
            criteria_metadata = []

            if self.db and citations:
                # title 기반으로 Criteria 조회
                for citation in citations:
                    title = citation.get("title", "")
                    if title:
                        # DB에서 title로 criteria 찾기
                        result_criteria = await self.db.execute(
                            select(Criteria).where(
                                Criteria.title.like(f"%{title}%"),
                                Criteria.status == "active"
                            ).limit(1)
                        )
                        criteria = result_criteria.scalar_one_or_none()

                        if criteria:
                            if criteria.id not in criteria_ids:
                                criteria_ids.append(criteria.id)
                                criteria_metadata.append({
                                    "id": criteria.id,
                                    "title": criteria.title,
                                    "file_path": criteria.file_path
                                })

            # context_text를 구조화된 Markdown 형식으로 변환
            formatted_text = self.format_context_as_markdown(response_text, citations)

            return {
                "context_text": formatted_text,  # 포맷팅된 텍스트 사용
                "criteria_ids": criteria_ids,
                "criteria_metadata": criteria_metadata,
                "citations": citations
            }

        except Exception as e:
            logger.error(f"평가 기준 컨텍스트 검색 실패: {str(e)}")
            # 오류 발생 시 빈 컨텍스트 반환 (QnA 진행에는 영향 없도록)
            return {
                "context_text": "",
                "criteria_ids": [],
                "criteria_metadata": [],
                "citations": []
            }
