"""
QnA 서비스
Gemini API를 사용한 질문답변 처리 (FileSearch RAG)
"""
import logging
import time
from typing import Optional, Any
from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.documents import Document
from app.models.prompts import SystemPrompt
from app.models.qa_logs import QALog

logger = logging.getLogger(__name__)


class QnAService:
    """QnA 서비스 클래스 (FileSearch RAG)"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.qna_model_name = settings.GEMINI_QNA_MODEL
        self.client = genai.Client(api_key=settings.GOOGLE_API_KEY)

    async def ask_question(
        self,
        document: Document,
        question: str,
        user_id: int,
        conversation_history: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        """
        문서 기반 질문답변 (FileSearch RAG)

        Args:
            document: 문서 객체
            question: 질문
            user_id: 사용자 ID
            conversation_history: 대화 히스토리

        Returns:
            답변 및 메타데이터 (citations 포함)
        """
        start_time = time.time()

        try:
            # 활성 QnA 시스템 프롬프트 가져오기
            prompt = await self._get_active_prompt("qna")

            if not prompt:
                raise ValueError("활성 QnA 프롬프트를 찾을 수 없습니다")

            # FileSearch 호출 로그 (store_id 기반 검색)
            logger.info(
                f"QnA FileSearch 호출 (store_id 기반)",
                extra={
                    "user_id": user_id,
                    "document_id": document.id,
                    "store_id": document.store_id,
                }
            )

            # 평가 기준 컨텍스트 검색
            from app.services.criteria_context_service import CriteriaContextService
            criteria_service = CriteriaContextService()
            
            criteria_context = ""
            try:
                criteria_results = await criteria_service.get_context(question)
                if criteria_results:
                    criteria_texts = []
                    for item in criteria_results:
                        content = item.get("content", "")
                        if content:
                            criteria_texts.append(content)
                    
                    if criteria_texts:
                        criteria_context = "\n\n[관련 평가 기준]\n" + "\n---\n".join(criteria_texts)
                        logger.info(f"평가 기준 컨텍스트 추가됨: {len(criteria_texts)}개 항목")
            except Exception as e:
                logger.warning(f"평가 기준 검색 중 오류 발생 (무시됨): {e}")

            # 컨텍스트 구성 (문서 정보 제외, FileSearch가 자동 처리)
            # 평가 기준을 시스템 프롬프트 뒤에 추가
            full_prompt_content = f"{prompt.content}{criteria_context}"
            
            context = self._build_context(
                full_prompt_content, conversation_history
            )

            # FileSearch 도구와 함께 질문 전송 (store_id만 사용)
            response = self.client.models.generate_content(
                model=self.qna_model_name,
                contents=f"{context}\n\n질문: {question}",
                config=types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(
                                file_search_store_names=[document.store_id],
                                # metadata_filter=f"metadata.user_id = '{document.user_id}'"
                            )
                        )
                    ],
                    temperature=settings.QNA_TEMPERATURE
                )
            )

            answer = response.text

            # Citation 정보 추출
            citations = None
            sources_count = 0

            if response.candidates and response.candidates[0].grounding_metadata:
                grounding = response.candidates[0].grounding_metadata

                # GroundingMetadata 객체를 JSON serializable dict로 변환
                try:
                    # 재귀적으로 객체를 dict로 변환하는 함수
                    def to_serializable(obj):
                        if hasattr(obj, 'to_dict'):
                            return obj.to_dict()
                        elif hasattr(obj, '__dict__'):
                            result = {}
                            for key, value in vars(obj).items():
                                if isinstance(value, list):
                                    result[key] = [to_serializable(item) for item in value]
                                elif hasattr(value, '__dict__') or hasattr(value, 'to_dict'):
                                    result[key] = to_serializable(value)
                                else:
                                    result[key] = value
                            return result
                        else:
                            return str(obj)

                    citations = to_serializable(grounding)

                    # sources_count 계산
                    if isinstance(citations, dict) and 'grounding_chunks' in citations:
                        sources_count = len(citations.get('grounding_chunks', []))
                    elif isinstance(citations, dict):
                        sources_count = len(citations)
                    else:
                        sources_count = 1 if citations else 0

                    logger.info(f"검색된 Citations: {sources_count}개")
                except Exception as e:
                    logger.error(f"Citations 추출 실패: {str(e)}")
                    citations = {"error": str(e), "raw": str(grounding)}
                    sources_count = 0

            latency_ms = int((time.time() - start_time) * 1000)

            # QA 로그 저장
            await self._save_qa_log(
                document_id=document.id,
                user_id=user_id,
                prompt_id=prompt.id,
                question=question,
                answer=answer,
                model_name=self.qna_model_name,
                latency_ms=latency_ms,
                citations=citations,
                sources_count=sources_count,
            )

            logger.info(
                f"QnA 완료: doc={document.id}, "
                f"latency={latency_ms}ms, sources={sources_count}"
            )

            return {
                "question": question,
                "answer": answer,
                "latency_ms": latency_ms,
                "citations": citations,
                "grounding_metadata": {
                    "search_performed": bool(citations),
                    "sources_count": sources_count
                }
            }

        except Exception as e:
            logger.error(f"QnA 처리 실패: {str(e)}")
            raise

    def _build_context(
        self,
        system_prompt: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> str:
        """대화 컨텍스트 구성 (문서 정보는 FileSearch가 자동 처리)"""
        context_parts = [f"시스템 프롬프트: {system_prompt}"]

        # 대화 히스토리 추가
        if conversation_history:
            context_parts.append("\n이전 대화:")
            for conv in conversation_history[-5:]:  # 최근 5개만
                context_parts.append(
                    f"Q: {conv.get('question', '')}\n"
                    f"A: {conv.get('answer', '')}"
                )

        return "\n".join(context_parts)

    async def _get_active_prompt(
        self, prompt_type: str
    ) -> Optional[SystemPrompt]:
        """활성 시스템 프롬프트 가져오기"""
        result = await self.db.execute(
            select(SystemPrompt).where(
                SystemPrompt.type == prompt_type,
                SystemPrompt.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def _save_qa_log(
        self,
        document_id: int,
        user_id: int,
        prompt_id: int,
        question: str,
        answer: str,
        model_name: str,
        latency_ms: int,
        citations: Optional[list] = None,
        sources_count: int = 0,
    ) -> None:
        """QA 로그 저장 (Citations 포함)"""
        qa_log = QALog(
            document_id=document_id,
            user_id=user_id,
            prompt_id=prompt_id,
            question=question,
            answer=answer,
            model_name=model_name,
            latency_ms=latency_ms,
            citations=citations,
            sources_count=sources_count,
        )
        self.db.add(qa_log)
        await self.db.flush()

    async def get_qa_history(
        self, document_id: int, user_id: int, limit: int = 10
    ) -> list[QALog]:
        """QA 히스토리 가져오기"""
        result = await self.db.execute(
            select(QALog)
            .where(
                QALog.document_id == document_id,
                QALog.user_id == user_id,
            )
            .order_by(QALog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
