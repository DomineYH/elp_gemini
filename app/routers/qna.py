"""
QnA 라우터
세션 기반 질문답변 엔드포인트
"""
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.db import get_db
from app.dependencies import get_current_user
from app.models.users import User
from app.models.chat_sessions import ChatSession
from app.schemas.sessions import (
    CreateSessionRequest,
    CreateSessionResponse,
    AskQuestionRequest,
    AskQuestionResponse,
    ChatHistoryResponse,
    ChatMessageResponse,
)
from app.services.qna_service import QnAService

router = APIRouter(prefix="/api/qna", tags=["QnA"])
logger = logging.getLogger(__name__)


@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="QnA 세션 생성",
    description="지도안 기반 QnA 세션을 생성합니다.",
)
async def create_session(
    request: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    QnA 세션 생성

    Args:
        request: 세션 생성 요청
        current_user: 현재 로그인한 사용자
        db: 데이터베이스 세션

    Returns:
        생성된 세션 정보

    Raises:
        HTTPException: 세션 생성 실패
    """
    try:
        qna_service = QnAService(db)

        # 세션 생성 (title에 지도안 파일명, user_type에 사용자 유형 저장)
        session = await qna_service.create_session(
            user_id=current_user.id,
            title=request.lessonplan_filename,
            user_type=current_user.username,
        )
        await db.commit()

        logger.info(
            f"QnA 세션 생성: "
            f"session_id={session.id}, "
            f"user={current_user.username}, "
            f"file={request.lessonplan_filename}"
        )

        return CreateSessionResponse(
            session_id=session.id,
            user_id=session.user_id,
            lessonplan_filename=request.lessonplan_filename,
            created_at=session.created_at,
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            f"QnA 세션 생성 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="세션 생성 중 오류가 발생했습니다."
        )


@router.post(
    "/sessions/{session_id}/ask",
    response_model=AskQuestionResponse,
    summary="질문하기",
    description="세션에서 질문을 하고 답변을 받습니다.",
)
async def ask_question(
    session_id: int,
    request: AskQuestionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    질문하기

    Args:
        session_id: 세션 ID
        request: 질문 요청
        current_user: 현재 로그인한 사용자
        db: 데이터베이스 세션

    Returns:
        답변 정보

    Raises:
        HTTPException: 세션 없음 또는 답변 생성 실패
    """
    try:
        qna_service = QnAService(db)

        # 질문 처리
        result = await qna_service.ask_question(
            session_id=session_id,
            question=request.question,
            user_id=current_user.id,
            username=current_user.username,
        )
        await db.commit()

        logger.info(
            f"QnA 질문 처리: "
            f"session_id={session_id}, "
            f"user={current_user.username}"
        )

        return AskQuestionResponse(
            session_id=session_id,
            question=result["question"],
            answer=result["answer"],
            latency_ms=result.get("latency_ms"),
            citations=result.get("citations"),
        )

    except ValueError as e:
        await db.rollback()
        logger.warning(f"QnA 질문 처리 실패 (잘못된 요청): {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"QnA 질문 처리 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="질문 처리 중 오류가 발생했습니다."
        )


@router.get(
    "/sessions/{session_id}/history",
    response_model=ChatHistoryResponse,
    summary="대화 히스토리 조회",
    description="세션의 대화 히스토리를 조회합니다.",
)
async def get_chat_history(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    대화 히스토리 조회

    Args:
        session_id: 세션 ID
        current_user: 현재 로그인한 사용자
        db: 데이터베이스 세션

    Returns:
        대화 히스토리

    Raises:
        HTTPException: 세션 없음 또는 조회 실패
    """
    try:
        qna_service = QnAService(db)

        # 대화 히스토리 가져오기
        messages = await qna_service.get_conversation_history(
            session_id=session_id,
            limit=100,  # 전체 히스토리
        )

        # 응답 모델로 변환
        message_responses = [
            ChatMessageResponse(
                id=msg.id,
                session_id=msg.session_id,
                role=msg.role.value,
                content=msg.content,
                created_at=msg.created_at,
            )
            for msg in messages
        ]

        return ChatHistoryResponse(
            session_id=session_id,
            messages=message_responses,
            total_count=len(message_responses),
        )

    except Exception as e:
        logger.error(
            f"대화 히스토리 조회 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="히스토리 조회 중 오류가 발생했습니다."
        )


@router.post(
    "/{document_id:path}",
    response_model=AskQuestionResponse,
    summary="문서와 대화하기",
    description="문서 ID를 기반으로 세션을 자동 생성/조회하여 질문합니다.",
)
async def chat_with_document(
    document_id: str,
    request: AskQuestionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    문서와 대화하기 (세션 자동 관리)

    Args:
        document_id: 문서 ID (전체 경로)
        request: 질문 요청
        current_user: 현재 로그인한 사용자
        db: 데이터베이스 세션

    Returns:
        답변 정보
    """
    try:
        qna_service = QnAService(db)

        # 1. 해당 문서에 대한 기존 세션 찾기
        # title에 document_id를 저장한다고 가정
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.user_id == current_user.id,
                ChatSession.title == document_id
            ).order_by(ChatSession.updated_at.desc()).limit(1)
        )
        session = result.scalar_one_or_none()

        # 2. 세션이 없으면 생성
        if not session:
            session = await qna_service.create_session(
                user_id=current_user.id,
                title=document_id,
                user_type=current_user.username,
            )
            await db.commit()
            logger.info(f"새 세션 자동 생성: {session.id} for {document_id}")

        # 3. 질문 처리
        # document_id 예: fileSearchStores/user222store-j74m2v137dyv/documents/curicurumpdf-wm724i901oft
        # 여기서 store_id 추출: fileSearchStores/user222store-j74m2v137dyv
        store_id = None
        if "fileSearchStores/" in document_id and "/documents/" in document_id:
            parts = document_id.split("/documents/")
            store_id = parts[0]

        result = await qna_service.ask_question(
            session_id=session.id,
            question=request.question,
            user_id=current_user.id,
            username=current_user.username,
            store_id=store_id,
        )
        await db.commit()

        return AskQuestionResponse(
            session_id=session.id,
            question=result["question"],
            answer=result["answer"],
            latency_ms=result.get("latency_ms"),
            citations=result.get("citations"),
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            f"문서 대화 처리 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"대화 처리 중 오류가 발생했습니다: {str(e)}"
        )
