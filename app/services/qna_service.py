"""
QnA 서비스
Gemini API를 사용한 질문답변 처리 (FileSearch RAG)
세션 기반 대화 관리 및 ChatMessage 저장
"""

import asyncio
import logging
import re
import time
from typing import Any, List, Optional

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.repositories.app_state_repository import (
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    SYNC_STATE_NEEDS_RESYNC,
)
from app.services.file_search_service import FileSearchService
from app.services.lessonplan_analysis_service import (
    _LESSONPLAN_RETRIEVE_QUERY,
)
from app.services.prompt_loader_service import PromptLoaderService

logger = logging.getLogger(__name__)


def _chunk_titles(citations: Any) -> list:
    """로그용: citations의 grounding_chunks 출처 제목 목록."""
    if not isinstance(citations, dict):
        return []
    return [
        (chunk.get("retrieved_context") or {}).get("title")
        for chunk in citations.get("grounding_chunks") or []
        if isinstance(chunk, dict)
    ]


async def _mark_criteria_filter_needs_resync(
    app_state_repo: Any, exc: Exception
) -> None:
    try:
        await app_state_repo.set(KEY_SYNC_STATE, SYNC_STATE_NEEDS_RESYNC)
        await app_state_repo.set(KEY_SYNC_ERROR, str(exc))
    except Exception:
        logger.warning("평가기준 동기화 필요 상태 표시 실패", exc_info=True)


# 답변에 새어 나온 File Search 내부 식별자 (#174)
_STORE_PATH_RE = re.compile(r"fileSearchStores/[A-Za-z0-9_\-./]+")
# 한글 조사가 바로 붙으므로 \b 대신 ASCII 경계를 쓴다
_USER_STORE_RE = re.compile(
    r"(?<![A-Za-z0-9])user[-_]?\d*[-_]?store(?:-[a-z0-9]+)?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_RUBRIC_STORE_RE = re.compile(
    r"(?<![A-Za-z0-9])rubric[-_]?store(?:-[a-z0-9]+)?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_INTERNAL_ID_RE = re.compile(
    "|".join(
        p.pattern for p in (_STORE_PATH_RE, _USER_STORE_RE, _RUBRIC_STORE_RE)
    ),
    re.IGNORECASE,
)
_PAREN_INTERNAL_ID_RE = re.compile(
    r"\s*[(\[]\s*(?:" + _INTERNAL_ID_RE.pattern + r")\s*[)\]]",
    re.IGNORECASE,
)


def strip_internal_store_ids(text: Optional[str]) -> Optional[str]:
    """
    답변에서 File Search 스토어·문서 이름을 지운다 (#174).

    괄호 속 식별자는 괄호째 지우고, 본문 속 식별자는 역할 이름으로 바꾼다.
    """
    if not text:
        return text
    text = _PAREN_INTERNAL_ID_RE.sub("", text)
    text = _STORE_PATH_RE.sub("업로드 문서", text)
    text = _RUBRIC_STORE_RE.sub("평가기준 문서", text)
    return _USER_STORE_RE.sub("업로드하신 지도안", text)


# 저장·응답 citations에서 지우는 내부 경로 키 (#206)
_INTERNAL_CITATION_KEYS = {"uri", "document_name", "file_path"}


def _drop_internal_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_internal_keys(item)
            for key, item in value.items()
            if key not in _INTERNAL_CITATION_KEYS
        }
    if isinstance(value, list):
        return [_drop_internal_keys(item) for item in value]
    return value


def citation_source_titles(
    citations: Any, document_title: Optional[str]
) -> list[str]:
    """
    답변 출처 제목: 평가기준 표시명 + 지도안 제목 (#206).

    grounding title은 ASCII화된 업로드 이름이라 쓰지 않는다.
    """
    if not isinstance(citations, dict):
        return []
    titles = [
        c.get("title")
        for c in citations.get("criteria") or []
        if isinstance(c, dict)
    ]
    documents = citations.get("documents")
    if isinstance(documents, dict) and documents.get("grounding_chunks"):
        titles.append(document_title)
    return list(dict.fromkeys(t for t in titles if isinstance(t, str) and t))


class QnAService:
    """QnA 서비스 클래스 (세션 기반 FileSearch RAG)"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.qna_model_name = settings.GEMINI_QNA_MODEL
        self.client = genai.Client(
            api_key=settings.GOOGLE_API_KEY,
            http_options=types.HttpOptions(
                api_version="v1beta",
                timeout=settings.GEMINI_HTTP_TIMEOUT_MS,
            ),
        )
        self.prompt_loader = PromptLoaderService()
        self.file_search_service = FileSearchService()

    async def ask_question(
        self,
        session_id: int,
        question: str,
        user_id: int,
        username: str,
    ) -> dict[str, Any]:
        """
        세션 기반 질문답변 (FileSearch RAG)

        Args:
            session_id: 채팅 세션 ID
            question: 질문
            user_id: 사용자 ID
            username: 사용자 이름 (로깅용)

        Returns:
            답변 및 메타데이터 (citations 포함)
        """
        start_time = time.time()

        try:
            # 세션 존재 확인
            session = await self._get_session(session_id, user_id)
            if not session:
                raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")

            # QnA 시스템 프롬프트 로드
            system_prompt = self.prompt_loader.get_prompt("qna")
            if not system_prompt:
                raise ValueError("QnA 프롬프트를 찾을 수 없습니다")

            # 대화 히스토리 가져오기
            conversation_history = await self.get_conversation_history(
                session_id, limit=5
            )

            # 평가 기준 컨텍스트 검색
            from app.repositories.app_state_repository import AppStateRepository
            from app.services.criteria_context_service import (
                CriteriaContextService,
                build_criteria_context_or_notice,
            )

            criteria_service = CriteriaContextService(db=self.db)
            app_state_repo = AppStateRepository(db=self.db)

            criteria_context = ""
            criteria_ids = []
            criteria_metadata = []
            criteria_notice = None
            try:
                criteria_result, criteria_notice = (
                    await build_criteria_context_or_notice(
                        app_state_repo=app_state_repo,
                        criteria_context_service=criteria_service,
                        question=question,
                    )
                )

                if criteria_result:
                    context_text = criteria_result.get("context_text", "")
                    criteria_ids = criteria_result.get("criteria_ids", [])
                    criteria_metadata = criteria_result.get(
                        "criteria_metadata", []
                    )

                    if context_text:
                        # Vector Search 참고 자료만 포함 (시스템 규칙은 prompt.md에 있음)
                        criteria_context = (
                            "\n\n### [참고 자료: Vector Search로 검색된 평가기준 컨텍스트]\n\n"
                            "아래는 질문과 관련하여 미리 검색된 평가기준 내용입니다. "
                            "평가/분석 요청 시에만 참고하세요.\n\n"
                            + context_text
                        )
                        logger.info(
                            f"평가 기준 컨텍스트 추가: "
                            f"{len(criteria_ids)}개 평가기준"
                        )
            except Exception as e:
                logger.warning(f"평가 기준 검색 중 오류 (무시): {e}")

            # 질문 유형 분석 및 메타데이터 필터 결정
            from app.services.question_analyzer import QuestionAnalyzer

            analyzer = QuestionAnalyzer()
            question_analysis = analyzer.analyze_question(question)
            metadata_filter = question_analysis["metadata_filter"]
            is_evaluation = question_analysis["question_type"] == "evaluation"

            active_rubric_filter = None
            if is_evaluation and not criteria_notice:
                from app.services.criteria_vector_service import (
                    CriteriaVectorService,
                )

                try:
                    active_rubric_filter = (
                        await CriteriaVectorService.active_stable_id_filter(
                            client=self.client,
                            store_display_name=settings.FS_RUBRIC_STORE_NAME,
                        )
                    )
                except Exception as e:
                    logger.warning(
                        f"활성 평가기준 필터 조회 실패 (무시): {e}",
                        exc_info=True,
                    )
                    criteria_notice = "평가기준 동기화가 필요합니다."
                    await _mark_criteria_filter_needs_resync(app_state_repo, e)
                if not criteria_notice and not active_rubric_filter:
                    criteria_notice = "활성 평가기준이 없습니다."

            logger.info(
                f"질문 분석 완료\n"
                f"  - 질문 유형: {question_analysis['question_type']}\n"
                f"  - 평가 요청 여부: {is_evaluation}\n"
                f"  - 메타데이터 필터: {metadata_filter if metadata_filter else '없음 (모든 스토어 검색)'}"
            )

            # Store ID 결정
            try:
                if criteria_notice or not is_evaluation:
                    user_store_id = self.file_search_service.get_user_store_id(
                        user_key=user_id
                    )
                    rubric_store_id = None
                    store_ids = [user_store_id]
                    if criteria_notice:
                        logger.info(
                            "평가기준 사용 불가: 사용자 Store만 조회: %s",
                            store_ids,
                        )
                    else:
                        logger.info(
                            "일반 질문: 사용자 Store만 조회: %s",
                            store_ids,
                        )
                else:
                    # 사용자 스토어와 평가기준 스토어 모두 가져오기
                    store_ids = self.file_search_service.get_dual_store_ids(
                        user_key=user_id
                    )
                    logger.info(f"🎯 Store 조회 완료: {store_ids}")

                    # Store ID 분리 (첫 번째: user store, 두 번째: rubric store)
                    user_store_id = store_ids[0]
                    rubric_store_id = store_ids[1]

            except ValueError as e:
                logger.error(f"❌ Store 조회 실패: {e}")
                raise Exception(
                    "문서 스토어를 찾을 수 없습니다. " "관리자에게 문의하세요."
                )
            except Exception as e:
                logger.error(f"❌ 예상치 못한 오류: {e}")
                raise

            # Store 역할 명시 프롬프트 구성
            # 스토어 이름은 모델이 답변에 그대로 인용하므로 넣지 않는다 (#174)
            if is_evaluation and not criteria_notice:
                # 평가 요청: 평가기준 문서는 참고 자료, 지도안은 평가 대상
                store_role_prompt = (
                    "\n\n**평가기준 문서를 참고하여 사용자가 업로드한 "
                    "수업 지도안에 대해서 답해주세요.**\n\n"
                    "**중요 지시사항:**\n"
                    "- 평가기준 문서의 자료는 **답변 생성의 참고 자료**로만 "
                    "사용하세요.\n"
                    "- 사용자가 업로드한 수업 지도안만 "
                    "**질의 응답 대상**입니다.\n"
                    "- 답변 근거는 반드시 지도안에서 찾으세요. 지도안의 "
                    "표·평가 계획·활동 등을 먼저 검색하고, 찾지 못했을 때만 "
                    "지도안에 없다고 답하세요.\n"
                    "- File Search 스토어·문서 이름 등 내부 식별자는 답변에 "
                    "쓰지 마세요.\n"
                )
            else:
                # 일반 질문: 사용자 문서만 검색
                store_role_prompt = (
                    "\n\n**중요 지시사항:**\n"
                    "- 사용자가 업로드한 수업 지도안을 기반으로 답변하세요.\n"
                    "- File Search 스토어·문서 이름 등 내부 식별자는 답변에 "
                    "쓰지 마세요.\n"
                )

            # 대화 히스토리 구성
            history_context = ""
            if conversation_history:
                history_context = "\n\n**이전 대화:**\n"
                for conv in conversation_history:
                    past = strip_internal_store_ids(conv.get("answer", ""))
                    history_context += (
                        f"Q: {conv.get('question', '')}\nA: {past}\n"
                    )

            # Contents 구성: Store 역할 명시 + 평가기준 컨텍스트 + 히스토리 + 질문
            notice_text = f"\n\n[{criteria_notice}]" if criteria_notice else ""
            contents = (
                f"{store_role_prompt}"
                f"{criteria_context}"
                f"{notice_text}"
                f"{history_context}"
                f"\n\n**질문:** {question}"
            )

            # FileSearch 도구와 함께 질문 전송
            logger.info(
                f"QnA FileSearch 호출\n"
                f"  - session_id: {session_id}\n"
                f"  - user_id: {user_id}\n"
                f"  - username: {username}\n"
                f"  - User Store: {user_store_id}\n"
                f"  - Rubric Store: {rubric_store_id}\n"
                f"  - 평가 요청: {is_evaluation}\n"
                f"  - 메타데이터 필터: {active_rubric_filter or metadata_filter or '미적용'}"
            )

            # FileSearch 설정 구성
            user_file_search_config = {
                "file_search_store_names": [user_store_id]
            }
            if metadata_filter and not is_evaluation:
                user_file_search_config["metadata_filter"] = metadata_filter

            user_tool = types.Tool(
                file_search=types.FileSearch(**user_file_search_config)
            )
            file_search_tools = [user_tool]
            # 평가성 질문은 분석 경로(#118)처럼 2-패스: 이중 도구는 모델이
            # rubric만 검색해 지도안 청크를 놓친다 (#199)
            lesson_text, pass1_citations = "", None
            two_pass = bool(
                is_evaluation and active_rubric_filter and rubric_store_id
            )
            if two_pass:
                rubric_tool = types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[rubric_store_id],
                        metadata_filter=active_rubric_filter,
                    )
                )
                try:
                    pass1 = await asyncio.to_thread(
                        self.client.models.generate_content,
                        model=self.qna_model_name,
                        contents=_LESSONPLAN_RETRIEVE_QUERY,
                        config=types.GenerateContentConfig(
                            tools=[user_tool],
                            temperature=0.2,
                        ),
                    )
                    lesson_text = (pass1.text or "").strip()
                    if (
                        pass1.candidates
                        and pass1.candidates[0].grounding_metadata
                    ):
                        pass1_citations = self._extract_citations(
                            pass1.candidates[0].grounding_metadata
                        )
                    logger.info(
                        "QnA 1패스 지도안 원문 %d자: %.300s",
                        len(lesson_text),
                        lesson_text,
                    )
                    logger.info(
                        "QnA 1패스 grounding titles: %s",
                        _chunk_titles(pass1_citations),
                    )
                except Exception:
                    logger.warning(
                        "QnA 1패스 실패, 이중 도구로 폴백", exc_info=True
                    )
                if lesson_text:
                    contents += (
                        "\n\n**질의 대상 수업 지도안 원문 "
                        "(답변 근거는 반드시 여기서 찾으세요):**"
                        f"\n---\n{lesson_text}\n---"
                    )
                    file_search_tools = [rubric_tool]
                else:
                    file_search_tools.append(rubric_tool)

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.qna_model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,  # 시스템 프롬프트를 별도로 분리
                    tools=file_search_tools,
                    temperature=settings.QNA_TEMPERATURE,
                ),
            )

            answer = strip_internal_store_ids(response.text)

            # Citation 정보 추출
            citations = None
            sources_count = 0

            if (
                response.candidates
                and response.candidates[0].grounding_metadata
            ):
                grounding = response.candidates[0].grounding_metadata
                citations = self._extract_citations(grounding)

            if two_pass:
                logger.info(
                    "QnA 2패스 grounding titles: %s",
                    _chunk_titles(citations),
                )
            # 1패스 청크는 뒤에 붙인다: 앞에 넣으면 grounding_supports
            # 의 chunk 인덱스가 어긋난다
            pass1_chunks = (pass1_citations or {}).get("grounding_chunks")
            if pass1_chunks:
                citations = citations if isinstance(citations, dict) else {}
                chunks = list(citations.get("grounding_chunks") or [])
                citations["grounding_chunks"] = chunks + pass1_chunks

            if citations:
                if (
                    isinstance(citations, dict)
                    and "grounding_chunks" in citations
                ):
                    sources_count = len(citations.get("grounding_chunks", []))
                elif isinstance(citations, dict):
                    sources_count = len(citations)
                else:
                    sources_count = 1 if citations else 0

                logger.info(f"검색된 Citations: {sources_count}개")

            citations = _drop_internal_keys(citations)
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
                # 테스트 대역 세션에는 title이 없을 수 있다
                "sources": citation_source_titles(
                    extended_citations, getattr(session, "title", None)
                ),
                "criteria_notice": criteria_notice,
                "grounding_metadata": {
                    "search_performed": bool(citations),
                    "sources_count": sources_count,
                },
            }

        except Exception as e:
            logger.error(f"QnA 처리 실패: {str(e)}")
            raise

    def _extract_citations(self, grounding_metadata: Any) -> Optional[dict]:
        """
        Citation 정보 추출

        Args:
            grounding_metadata: Grounding 메타데이터

        Returns:
            직렬화된 Citation 딕셔너리
        """
        try:

            def to_serializable(obj):
                if hasattr(obj, "to_dict"):
                    return obj.to_dict()
                elif hasattr(obj, "__dict__"):
                    result = {}
                    for key, value in vars(obj).items():
                        if isinstance(value, list):
                            result[key] = [
                                to_serializable(item) for item in value
                            ]
                        elif hasattr(value, "__dict__") or hasattr(
                            value, "to_dict"
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
            return None

    def _extend_citations(
        self, citations: Optional[dict], criteria_metadata: list[dict[str, Any]]
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
            result = {"documents": citations or {}, "criteria": []}

            # 평가기준 출처 추가
            for criteria in criteria_metadata:
                result["criteria"].append(
                    {
                        "id": criteria.get("id"),
                        "title": criteria.get("title"),
                        "type": "criteria",
                    }
                )

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

    def _build_context(
        self,
        system_prompt: str,
        conversation_history: Optional[List[dict]] = None,
    ) -> str:
        context = f"시스템 프롬프트: {system_prompt}"
        if conversation_history:
            context += "\n\n이전 대화:"
            for conv in conversation_history:
                context += (
                    f"\nQ: {conv.get('question', '')}"
                    f"\nA: {conv.get('answer', '')}"
                )
        return context

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
                    history.append(
                        {
                            "question": messages[i].content,
                            "answer": messages[i + 1].content,
                        }
                    )

        return history[-limit:]  # 최근 limit개만

    async def create_session(
        self,
        user_id: int,
        title: Optional[str] = None,
        user_type: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> ChatSession:
        """
        새 세션 생성

        Args:
            user_id: 사용자 ID
            title: 세션 제목 (선택)
            user_type: 사용자 유형 (1학년, 2학년, 3학년, 4학년, 교사)
            document_id: 문서 대화 세션의 File Search 문서 경로 (선택)

        Returns:
            생성된 ChatSession
        """
        session = ChatSession(
            user_id=user_id,
            title=title,
            user_type=user_type,
            document_id=document_id,
        )
        self.db.add(session)
        await self.db.flush()

        logger.info(
            f"세션 생성: id={session.id}, user_id={user_id}, "
            f"user_type={user_type}"
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
