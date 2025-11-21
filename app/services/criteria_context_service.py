"""
평가 기준 컨텍스트 검색 서비스
활성 기준 문서에서 관련 컨텍스트를 검색하여 평가에 활용
"""
import logging
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types

from app.config import settings
from app.services.criteria_context_provider import (
    criteria_context_provider,
)

logger = logging.getLogger(__name__)


class CriteriaContextService:
    """
    평가 기준 컨텍스트 검색 서비스

    활성화된 기준 문서의 vector_store_id를 사용하여
    Google File Search Tool로 관련 컨텍스트를 검색합니다.
    """

    _client = None

    @classmethod
    def get_client(cls):
        """싱글톤 Client 인스턴스 반환"""
        if cls._client is None:
            cls._client = genai.Client(
                api_key=settings.GOOGLE_API_KEY
            )
        return cls._client

    def __init__(self):
        """
        CriteriaContextService 초기화

        Raises:
            ValueError: GOOGLE_API_KEY가 설정되지 않은 경우
        """
        if not settings.GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다"
            )

        self.client = self.get_client()

    async def get_context(
        self, query: str, k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        활성 기준 문서에서 관련 컨텍스트 검색

        Args:
            query: 검색 쿼리 (평가 대상 내용)
            k: 반환할 상위 컨텍스트 개수 (기본값: 5)

        Returns:
            검색된 컨텍스트 리스트
            각 항목: {
                "content": str,
                "score": float,
                "metadata": dict
            }

        Raises:
            ValueError: 활성 기준이 없을 때
            Exception: 검색 실패 시
        """
        # Active 기준 확인
        if not criteria_context_provider.has_active_criteria():
            logger.error("활성 평가 기준이 없습니다")
            raise ValueError(
                "활성화된 평가 기준이 없습니다. "
                "관리자에게 문의하세요."
            )

        vector_store_id = (
            criteria_context_provider
            .get_active_vector_store_id()
        )
        criteria_id = (
            criteria_context_provider.get_active_criteria_id()
        )

        logger.info(
            f"평가 기준 컨텍스트 검색 시작: "
            f"criteria_id={criteria_id}, query={query[:50]}..."
        )

        try:
            # Google File Search Tool로 검색 수행
            results = await self._search_vector_store(
                vector_store_id, query, k
            )

            logger.info(
                f"검색 완료: {len(results)}개 컨텍스트 반환 "
                f"(criteria_id={criteria_id})"
            )

            return results

        except Exception as e:
            logger.error(
                f"평가 기준 컨텍스트 검색 실패: {str(e)}"
            )
            raise

    async def _search_vector_store(
        self,
        vector_store_id: str,
        query: str,
        k: int,
    ) -> List[Dict[str, Any]]:
        """
        Vector Store에서 검색 수행

        Args:
            vector_store_id: 검색할 벡터 스토어 ID
            query: 검색 쿼리
            k: 반환할 결과 개수

        Returns:
            검색 결과 리스트

        Raises:
            Exception: 검색 API 호출 실패 시
        """
        try:
            # Gemini API로 File Search 수행
            # NOTE: 현재 Gemini SDK는 직접 검색 API를
            # 제공하지 않으므로 generate_content에
            # tool_config로 전달
            config = types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        file_search_tools=[
                            types.FileSearchTool(
                                file_search_stores=[
                                    vector_store_id
                                ]
                            )
                        ]
                    )
                ],
                temperature=0.0,  # 검색은 결정적으로
            )

            # 검색을 위한 프롬프트 구성
            search_prompt = (
                f"다음 내용과 관련된 평가 기준을 찾아주세요:\n\n"
                f"{query}\n\n"
                f"관련된 평가 기준 내용을 상위 {k}개 "
                f"추출해주세요."
            )

            response = self.client.models.generate_content(
                model=settings.GEMINI_EVAL_MODEL,
                contents=search_prompt,
                config=config,
            )

            # 검색 결과 파싱
            results = self._parse_search_results(response, k)

            logger.debug(
                f"Vector Store 검색 완료: "
                f"{len(results)}개 결과 반환"
            )

            return results

        except Exception as e:
            logger.error(
                f"Vector Store 검색 실패: {str(e)}"
            )
            raise

    def _parse_search_results(
        self, response: Any, k: int
    ) -> List[Dict[str, Any]]:
        """
        Gemini API 응답에서 검색 결과 파싱

        Args:
            response: Gemini API 응답
            k: 최대 반환 개수

        Returns:
            파싱된 컨텍스트 리스트
        """
        results = []

        try:
            # 응답에서 grounding_metadata 추출
            if hasattr(response, "candidates"):
                for candidate in response.candidates[:k]:
                    if hasattr(
                        candidate, "grounding_metadata"
                    ):
                        metadata = (
                            candidate.grounding_metadata
                        )

                        # 검색된 청크 정보 추출
                        if hasattr(
                            metadata, "search_entry_point"
                        ):
                            chunks = (
                                metadata
                                .search_entry_point
                                .rendered_content
                            )

                            results.append(
                                {
                                    "content": chunks,
                                    "score": 1.0,
                                    "metadata": {
                                        "source": "criteria"
                                    },
                                }
                            )

            # grounding_metadata가 없으면
            # 응답 텍스트 자체를 반환
            if not results and hasattr(response, "text"):
                results.append(
                    {
                        "content": response.text,
                        "score": 1.0,
                        "metadata": {"source": "criteria"},
                    }
                )

            logger.debug(
                f"검색 결과 파싱 완료: {len(results)}개"
            )

        except Exception as e:
            logger.warning(
                f"검색 결과 파싱 실패: {str(e)}, "
                f"응답 텍스트 반환"
            )
            # 파싱 실패 시 응답 텍스트 반환
            if hasattr(response, "text"):
                results.append(
                    {
                        "content": response.text,
                        "score": 1.0,
                        "metadata": {"source": "criteria"},
                    }
                )

        return results[:k]  # 최대 k개만 반환
