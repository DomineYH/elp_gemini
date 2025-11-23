"""
수업 지도안 분석 서비스
평가기준 기반 수업지도안 체계적 평가
"""
import asyncio
import logging
from typing import Dict, Any, Optional
from google import genai
from google.genai import types
from google.api_core import exceptions
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.prompt_loader_service import PromptLoaderService
from app.services.file_search_service import FileSearchService
from app.services.criteria_context_service import CriteriaContextService

logger = logging.getLogger(__name__)


class LessonPlanAnalysisService:
    """수업 지도안 분석 서비스"""

    def __init__(self, db: AsyncSession):
        """
        서비스 초기화

        Args:
            db: 비동기 DB 세션
        """
        self.db = db
        self.model_name = settings.GEMINI_EVAL_MODEL
        self.client = genai.Client(
            api_key=settings.GOOGLE_API_KEY,
            http_options={'api_version': 'v1beta'}
        )
        self.prompt_loader = PromptLoaderService()
        self.file_search_service = FileSearchService()
        self.criteria_service = CriteriaContextService(db=db)

    async def analyze_lesson_plan(
        self,
        session_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        수업 지도안 체계적 평가

        Args:
            session_id: 채팅 세션 ID
            user_id: 사용자 ID (Store ID 조회용)

        Returns:
            {
                "success": bool,
                "report": str,  # Markdown 보고서
                "citations": dict,  # Citation 정보
                "latency_ms": int  # 응답 시간 (ms)
            }
        """
        import time
        start_time = time.time()

        try:
            # 타임아웃 설정 (180초)
            async with asyncio.timeout(180):
                # 1. Vector Search (평가기준 컨텍스트)
                criteria_context = await self._get_criteria_context()
                logger.info("평가기준 컨텍스트 추출 완료")

                # 2. File Search Store ID 조회 (Phase 1 활용)
                store_ids = await self._get_store_ids(user_id)
                if not store_ids:
                    return {
                        "success": False,
                        "error": "분석할 문서가 없습니다. 수업 지도안을 먼저 업로드해주세요."
                    }
                logger.info(f"File Search Store 조회 완료: {store_ids}")

                # 3. 프롬프트 구성
                system_prompt = self.prompt_loader.get_prompt("lesson_analysis")
                full_prompt = self._build_analysis_prompt(
                    system_prompt, criteria_context
                )
                logger.info("프롬프트 구성 완료")

                # 4. Gemini API 호출 (File Search)
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        tools=[
                            types.Tool(
                                file_search=types.FileSearch(
                                    file_search_store_names=store_ids
                                )
                            )
                        ],
                        temperature=0.7
                    )
                )

                # 5. Markdown 보고서 추출 및 후처리
                raw_report = response.text if response.text else ""
                report = self._post_process_report(raw_report)  # 후처리 적용

                # 6. Citation 추출
                citations = self._extract_citations(response)

                # 응답 시간 계산
                latency_ms = int((time.time() - start_time) * 1000)

                logger.info(f"분석 완료 (응답 시간: {latency_ms}ms)")

                return {
                    "success": True,
                    "report": report,
                    "citations": citations,
                    "latency_ms": latency_ms
                }

        except asyncio.TimeoutError:
            logger.error("분석 타임아웃 (180초 초과)")
            return {"success": False, "error": "분석 시간 초과 (180초)"}

        except exceptions.GoogleAPIError as e:
            logger.error(f"Google API 오류: {e}")
            return {"success": False, "error": f"API 오류: {str(e)}"}

        except Exception as e:
            logger.error(f"분석 실패: {e}", exc_info=True)
            return {"success": False, "error": "분석 중 오류 발생"}

    async def _get_criteria_context(self) -> str:
        """
        평가기준 Vector Search

        Returns:
            평가기준 컨텍스트 문자열
        """
        try:
            context_data = await self.criteria_service.get_context(
                "수업 지도안 평가 기준"
            )
            # dictionary에서 context_text 추출
            if isinstance(context_data, dict):
                return context_data.get("context_text", "평가기준 컨텍스트 없음")
            return context_data if context_data else "평가기준 컨텍스트 없음"

        except Exception as e:
            logger.warning(f"평가기준 컨텍스트 추출 실패: {e}")
            return "평가기준 컨텍스트 없음"

    async def _get_store_ids(self, user_id: int) -> list[str]:
        """
        File Search Store ID 조회 (Phase 1 공통 유틸 사용)

        Args:
            user_id: 사용자 ID

        Returns:
            Store ID 리스트 [rubricstore, user-{user_id}-store]
        """
        try:
            # Phase 1의 get_dual_store_ids() 사용
            store_ids = self.file_search_service.get_dual_store_ids(
                user_id
            )
            logger.info(f"✅ Store ID 조회 완료: {len(store_ids)}개")
            return store_ids
        except ValueError as e:
            logger.error(f"❌ Store ID 조회 실패: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ 예상치 못한 오류: {e}")
            return []

    def _build_analysis_prompt(
        self,
        system_prompt: str,
        criteria_context: str
    ) -> str:
        """
        분석 프롬프트 구성

        Args:
            system_prompt: 시스템 프롬프트 (lesson_analysis)
            criteria_context: Vector Search 컨텍스트

        Returns:
            완전한 프롬프트
        """
        return f"""
{system_prompt}

### [참고 자료: 관련 평가 기준]
{criteria_context}

위 평가 기준을 바탕으로 사용자가 업로드한 수업 지도안을 다음 5개 항목으로 체계적으로 평가해주세요:

1. 교육과정 목표 및 성격과의 부합
2. 내용 체계 및 성취기준 달성
3. 교수·학습 방법의 적절성
4. 평가 방향과의 일치
5. 개선 및 보완을 위한 제안

반드시 Markdown 형식의 보고서로 작성해주세요.
"""

    def _post_process_report(self, report: str) -> str:
        """
        보고서 후처리 - "참고 자료" 섹션 가독성 개선

        Gemini가 구조화된 형식으로 출력하지 않았을 경우를 대비한 안전장치

        Args:
            report: 원본 Markdown 보고서

        Returns:
            후처리된 보고서
        """
        import re

        try:
            # "Vector Search 참고 자료" 섹션 찾기
            # 패턴: ### Vector Search 참고 자료 이후의 내용
            pattern = r'(###\s*Vector Search 참고 자료\s*\n)(.*?)(\n###|\Z)'

            match = re.search(pattern, report, flags=re.DOTALL)

            if not match:
                # 패턴이 없으면 원본 반환
                return report

            header = match.group(1)
            content = match.group(2).strip()
            next_section = match.group(3)

            # 이미 구조화되어 있는지 확인 (목록이나 번호가 있으면 이미 구조화됨)
            if re.search(r'^\s*[0-9]+\.|\s*-|\s*\*', content, re.MULTILINE):
                # 이미 구조화되어 있으면 원본 반환
                return report

            # 구조화되지 않은 긴 텍스트인 경우 재포맷팅
            if len(content) > 100:
                # 문장 단위로 분리
                sentences = re.split(r'(?<=[.!?])\s+', content)
                sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

                # 목록 형식으로 변환 (최대 8개 문장)
                formatted = "\n".join([f"- {s}" for s in sentences[:8]])

                # 재구성된 섹션으로 교체
                new_section = f"{header}\n{formatted}\n{next_section}"
                report = report[:match.start()] + new_section + report[match.end():]

            return report

        except Exception as e:
            logger.warning(f"보고서 후처리 실패 (원본 반환): {e}")
            return report

    def _extract_citations(self, response) -> Optional[dict]:
        """
        Citation 정보 추출 (QnA 패턴 재사용)

        Args:
            response: Gemini API 응답

        Returns:
            Citation 정보 딕셔너리
        """
        citations = {
            "used_criteria": [],
            "grounding_chunks": []
        }

        try:
            if (
                response.candidates
                and response.candidates[0].grounding_metadata
            ):
                grounding = response.candidates[0].grounding_metadata

                # Grounding chunks 처리
                if hasattr(grounding, "grounding_chunks"):
                    for chunk in grounding.grounding_chunks:
                        citation_info = {
                            "source": None,
                            "title": None,
                            "uri": None,
                        }

                        # Retrieved context (File Search) 처리
                        if (
                            hasattr(chunk, "retrieved_context")
                            and chunk.retrieved_context
                        ):
                            citation_info["source"] = "file_search"
                            citation_info["uri"] = (
                                chunk.retrieved_context.uri
                                if hasattr(chunk.retrieved_context, "uri")
                                else None
                            )
                            citation_info["title"] = (
                                chunk.retrieved_context.title
                                if hasattr(chunk.retrieved_context, "title")
                                else None
                            )

                        citations["grounding_chunks"].append(citation_info)

                logger.debug(f"Citations 추출 완료: {len(citations['grounding_chunks'])}개")

        except Exception as e:
            logger.warning(f"Citation 추출 실패: {e}")

        return citations
