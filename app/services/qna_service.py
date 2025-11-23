"""
QnA 서비스
Gemini API를 사용한 질문답변 처리 (FileSearch RAG)
세션 기반 대화 관리 및 ChatMessage 저장
"""
import logging
import time
from typing import Optional, Any, List, Dict
from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.chat_sessions import ChatSession
from app.models.chat_messages import ChatMessage, MessageRole
from app.services.prompt_loader_service import PromptLoaderService
from app.services.file_search_service import FileSearchService

logger = logging.getLogger(__name__)


class QnAService:
    """QnA 서비스 클래스 (세션 기반 FileSearch RAG)"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.qna_model_name = settings.GEMINI_QNA_MODEL
        self.client = genai.Client(
            api_key=settings.GOOGLE_API_KEY,
            http_options={'api_version': 'v1beta'}
        )
        self.prompt_loader = PromptLoaderService()
        self.file_search_service = FileSearchService()

    async def ask_question(
        self,
        session_id: int,
        question: str,
        user_id: int,
        store_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        세션 기반 질문답변 (FileSearch RAG)

        Args:
            session_id: 채팅 세션 ID
            question: 질문
            user_id: 사용자 ID
            store_id: 검색할 File Search Store ID (없으면 기본값 사용)

        Returns:
            답변 및 메타데이터 (citations 포함)
        """
        start_time = time.time()

        try:
            # 세션 존재 확인
            session = await self._get_session(session_id, user_id)
            if not session:
                raise ValueError(
                    f"세션을 찾을 수 없습니다: {session_id}"
                )

            # QnA 시스템 프롬프트 로드
            system_prompt = self.prompt_loader.get_prompt("qna")
            if not system_prompt:
                raise ValueError("QnA 프롬프트를 찾을 수 없습니다")

            # 대화 히스토리 가져오기
            conversation_history = (
                await self.get_conversation_history(
                    session_id, limit=5
                )
            )

            # 평가 기준 컨텍스트 검색
            from app.services.criteria_context_service import (
                CriteriaContextService
            )
            criteria_service = CriteriaContextService(db=self.db)

            criteria_context = ""
            criteria_ids = []
            criteria_metadata = []
            try:
                criteria_result = (
                    await criteria_service.get_context(question)
                )

                context_text = criteria_result.get("context_text", "")
                criteria_ids = criteria_result.get("criteria_ids", [])
                criteria_metadata = criteria_result.get("criteria_metadata", [])

                if context_text:
                    criteria_context = (
                        "\n\n### [참고 자료: 관련 평가 기준]\n"
                        "다음은 답변 생성 시 참고할 수 있는 평가 기준입니다. "
                        "이 기준을 직접 설명하기보다는, 문서 분석의 관점으로 활용하세요.\n\n"
                        + context_text
                    )
                    logger.info(
                        f"평가 기준 컨텍스트 추가: "
                        f"{len(criteria_ids)}개 평가기준"
                    )
            except Exception as e:
                logger.warning(
                    f"평가 기준 검색 중 오류 (무시): {e}"
                )

            # 전체 프롬프트 구성
            full_prompt = (
                f"{system_prompt}{criteria_context}"
            )
            context = self._build_context(
                full_prompt, conversation_history
            )

            # Store ID 결정 - 평가기준 스토어와 사용자 스토어 모두 사용
            # Vector Search는 평가기준 벡터 검색 (참고 자료)
            # File Search는 평가기준 스토어 + 사용자 스토어 검색 (주요 검색)
            store_ids = []

            # 1. 평가기준 스토어 (rubric store) 조회
            rubric_store_id = None
            try:
                # 스토어 목록에서 "rubricstore" 문자가 포함된 스토어 찾기
                for store in self.file_search_service.client.file_search_stores.list():
                    if "rubricstore" in store.display_name.lower():
                        rubric_store_id = store.name
                        store_ids.append(rubric_store_id)
                        logger.info(f"평가기준 스토어 발견: {store.display_name} ({rubric_store_id})")
                        break

                # 없으면 rubric_store_name으로 생성
                if not rubric_store_id:
                    rubric_store = self.file_search_service._get_or_create_store(
                        self.file_search_service.rubric_store_name
                    )
                    rubric_store_id = rubric_store.name
                    store_ids.append(rubric_store_id)
                    logger.info(f"평가기준 스토어 생성: {rubric_store.display_name} ({rubric_store_id})")
            except Exception as e:
                logger.warning(f"평가기준 스토어 조회 실패: {e}")

            # 2. 사용자 스토어 조회/생성
            user_store_id = None
            if store_id:
                # store_id가 제공된 경우 사용
                user_store_id = store_id
                store_ids.append(user_store_id)
                logger.info(f"제공된 사용자 스토어 사용: {user_store_id}")
            else:
                # 사용자별 스토어 찾기 또는 생성
                user_store_name = f"user-{user_id}-store"
                try:
                    # 스토어 목록에서 user{id}store 패턴 찾기
                    for store in self.file_search_service.client.file_search_stores.list():
                        if f"user{user_id}store" in store.display_name.lower() or user_store_name in store.display_name.lower():
                            user_store_id = store.name
                            store_ids.append(user_store_id)
                            logger.info(f"사용자 스토어 발견: {store.display_name} ({user_store_id})")
                            break

                    # 없으면 생성
                    if not user_store_id:
                        user_store = self.file_search_service._get_or_create_store(user_store_name)
                        user_store_id = user_store.name
                        store_ids.append(user_store_id)
                        logger.info(f"사용자 스토어 생성: {user_store_name} ({user_store_id})")
                except Exception as e:
                    logger.warning(f"사용자 스토어 접근 실패: {e}")

            # 최소한 하나의 스토어는 있어야 함
            if not store_ids:
                # 메인 스토어를 폴백으로 사용
                main_store = self.file_search_service._get_or_create_store(
                    self.file_search_service.main_store_name
                )
                store_ids.append(main_store.name)
                logger.warning(f"모든 스토어 조회 실패, 메인 스토어 사용: {main_store.name}")

            # FileSearch 도구와 함께 질문 전송 (평가기준 스토어 + 사용자 스토어 참조)
            logger.info(
                f"QnA FileSearch 호출\n"
                f"  - session_id: {session_id}\n"
                f"  - user_id: {user_id}\n"
                f"  - 평가기준 스토어: {rubric_store_id}\n"
                f"  - 사용자 스토어: {user_store_id}\n"
                f"  - 총 스토어 개수: {len(store_ids)}"
            )

            response = self.client.models.generate_content(
                model=self.qna_model_name,
                contents=f"{context}\n\n질문: {question}",
                config=types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(
                                file_search_store_names=store_ids
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

            if (
                response.candidates
                and response.candidates[0].grounding_metadata
            ):
                grounding = (
                    response.candidates[0].grounding_metadata
                )
                citations = self._extract_citations(grounding)

                if (
                    isinstance(citations, dict)
                    and 'grounding_chunks' in citations
                ):
                    sources_count = len(
                        citations.get('grounding_chunks', [])
                    )
                elif isinstance(citations, dict):
                    sources_count = len(citations)
                else:
                    sources_count = 1 if citations else 0

                logger.info(f"검색된 Citations: {sources_count}개")

            # Citations에 평가기준 출처 추가
            extended_citations = self._extend_citations(
                citations, criteria_metadata
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # 질문과 답변을 ChatMessage로 저장
            await self._save_messages(
                session_id=session_id,
                question=question,
                answer=answer,
                model_name=self.qna_model_name,
                citations=extended_citations,
                used_criteria_ids=criteria_ids,
            )

            logger.info(
                f"QnA 완료: session={session_id}, "
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
        conversation_history: Optional[List[dict]] = None,
    ) -> str:
        """대화 컨텍스트 구성"""
        context_parts = [f"시스템 프롬프트: {system_prompt}"]

        # 대화 히스토리 추가
        if conversation_history:
            context_parts.append("\n이전 대화:")
            for conv in conversation_history:
                context_parts.append(
                    f"Q: {conv.get('question', '')}\n"
                    f"A: {conv.get('answer', '')}"
                )

        return "\n".join(context_parts)

    def _extract_citations(
        self, grounding_metadata: Any
    ) -> Optional[dict]:
        """
        Citation 정보 추출

        Args:
            grounding_metadata: Grounding 메타데이터

        Returns:
            직렬화된 Citation 딕셔너리
        """
        try:
            def to_serializable(obj):
                if hasattr(obj, 'to_dict'):
                    return obj.to_dict()
                elif hasattr(obj, '__dict__'):
                    result = {}
                    for key, value in vars(obj).items():
                        if isinstance(value, list):
                            result[key] = [
                                to_serializable(item)
                                for item in value
                            ]
                        elif (
                            hasattr(value, '__dict__')
                            or hasattr(value, 'to_dict')
                        ):
                            result[key] = to_serializable(value)
                        else:
                            result[key] = value
                    return result
                else:
                    return str(obj)

            return to_serializable(grounding_metadata)
        except Exception as e:
            logger.error(f"Citations 추출 실패: {str(e)}")
            return {
                "error": str(e),
                "raw": str(grounding_metadata)
            }

    def _extend_citations(
        self,
        citations: Optional[dict],
        criteria_metadata: list[dict[str, Any]]
    ) -> dict:
        """
        Citations에 평가기준 출처 추가

        Args:
            citations: 기존 citations (문서 출처)
            criteria_metadata: 평가기준 메타데이터

        Returns:
            확장된 citations (문서 + 평가기준 출처)
        """
        try:
            result = {
                "documents": citations or {},
                "criteria": []
            }

            # 평가기준 출처 추가
            for criteria in criteria_metadata:
                result["criteria"].append({
                    "id": criteria.get("id"),
                    "title": criteria.get("title"),
                    "file_path": criteria.get("file_path"),
                    "type": "criteria"
                })

            return result
        except Exception as e:
            logger.error(f"Citations 확장 실패: {str(e)}")
            return {"documents": citations or {}, "criteria": []}

    async def _get_session(
        self, session_id: int, user_id: int
    ) -> Optional[ChatSession]:
        """
        세션 가져오기 및 권한 확인

        Args:
            session_id: 세션 ID
            user_id: 사용자 ID

        Returns:
            ChatSession 객체
        """
        result = await self.db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _save_messages(
        self,
        session_id: int,
        question: str,
        answer: str,
        model_name: str,
        citations: Optional[dict] = None,
        used_criteria_ids: Optional[List[int]] = None,
    ) -> None:
        """
        질문과 답변을 ChatMessage로 저장

        Args:
            session_id: 세션 ID
            question: 질문
            answer: 답변
            model_name: 모델 이름
            citations: Citation 정보
            used_criteria_ids: 사용된 평가기준 ID 목록
        """
        import json

        # 사용자 질문 저장
        user_message = ChatMessage(
            session_id=session_id,
            role=MessageRole.USER,
            content=question,
        )
        self.db.add(user_message)

        # 어시스턴트 답변 저장
        assistant_message = ChatMessage(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=answer,
            model_name=model_name,
            citations=citations,
            used_criteria_ids=json.dumps(used_criteria_ids or []),
        )
        self.db.add(assistant_message)

        await self.db.flush()

    async def get_conversation_history(
        self, session_id: int, limit: int = 10
    ) -> List[dict]:
        """
        세션의 대화 히스토리 가져오기

        Args:
            session_id: 세션 ID
            limit: 가져올 메시지 쌍 수 (기본 10)

        Returns:
            대화 히스토리 리스트
        """
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(limit * 2)  # 질문+답변 쌍
        )
        messages = list(result.scalars().all())

        # 질문-답변 쌍으로 변환
        history = []
        for i in range(0, len(messages), 2):
            if i + 1 < len(messages):
                if (
                    messages[i].role == MessageRole.USER
                    and messages[i + 1].role == MessageRole.ASSISTANT
                ):
                    history.append({
                        "question": messages[i].content,
                        "answer": messages[i + 1].content,
                    })

        return history[-limit:]  # 최근 limit개만

    async def create_session(
        self, user_id: int, title: Optional[str] = None
    ) -> ChatSession:
        """
        새 세션 생성

        Args:
            user_id: 사용자 ID
            title: 세션 제목 (선택)

        Returns:
            생성된 ChatSession
        """
        session = ChatSession(
            user_id=user_id,
            title=title,
        )
        self.db.add(session)
        await self.db.flush()

        logger.info(
            f"세션 생성: id={session.id}, user_id={user_id}"
        )
        return session

    async def get_user_sessions(
        self, user_id: int, limit: int = 20
    ) -> List[ChatSession]:
        """
        사용자의 세션 목록 가져오기

        Args:
            user_id: 사용자 ID
            limit: 가져올 세션 수

        Returns:
            ChatSession 리스트
        """
        result = await self.db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
