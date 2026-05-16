"""
QnA 라우터
세션 기반 질문답변 엔드포인트
"""
import logging
from datetime import datetime
from typing import Optional, cast

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db import get_db
from app.dependencies import get_current_user
from app.models.chat_messages import ChatMessage
from app.models.chat_sessions import ChatSession
from app.models.user_profiles import UserProfile
from app.models.users import User
from app.schemas.sessions import (
    AskQuestionRequest,
    AskQuestionResponse,
    ChatHistoryResponse,
    ChatMessageResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    UserSessionItem,
    UserSessionListResponse,
)

router = APIRouter(prefix="/api/qna", tags=["QnA"])
logger = logging.getLogger(__name__)

SESSION_LIST_DEFAULT_LIMIT = 50
SESSION_LIST_MAX_LIMIT = 100
CHAT_HISTORY_DEFAULT_LIMIT = 200
CHAT_HISTORY_MAX_LIMIT = 200


def _model_int(value: object) -> int:
    """Return SQLAlchemy model values as ints for type checkers."""
    return cast(int, value)


def _model_str(value: object) -> str:
    """Return SQLAlchemy model values as strings for type checkers."""
    return cast(str, value)


def _model_optional_str(value: object) -> Optional[str]:
    """Return SQLAlchemy model instance values as optional strings."""
    return cast(Optional[str], value)


def _model_datetime(value: object) -> datetime:
    """Return SQLAlchemy model instance values as concrete datetimes."""
    return cast(datetime, value)


def _has_more(offset: int, returned_count: int, total_count: int) -> bool:
    """Return whether a capped list response has another page."""
    return offset + returned_count < total_count


async def _session_segment_label_for_user(
    db: AsyncSession,
    current_user: User,
) -> str:
    """
    Store an analytics segment label, not an internal username, in
    ChatSession.user_type.

    Legacy invite-code sessions used grade/teacher labels in this column. New
    email/password users should continue that reporting contract through
    UserProfile metadata so admin filters do not depend on generated usernames.
    """
    result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id == _model_int(current_user.id)
        )
    )
    profile = result.scalar_one_or_none()

    if profile:
        profile_role = _model_optional_str(profile.role)
        if profile_role == "teacher":
            return "교사"
        if profile_role == "preservice_teacher":
            preservice_grade = cast(Optional[int], profile.preservice_grade)
            if preservice_grade:
                return f"{preservice_grade}학년"
            return "미지정"

    nickname = _model_optional_str(current_user.nickname) or ""
    if nickname == "teacher":
        return "교사"
    if nickname == "preservice_teacher":
        return "미지정"
    return nickname or "미지정"


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
        from app.services.qna_service import QnAService

        qna_service = QnAService(db)

        session_segment = await _session_segment_label_for_user(
            db, current_user
        )

        # 세션 생성 (title에 지도안 파일명, user_type에 세션 세그먼트 저장)
        session = await qna_service.create_session(
            user_id=_model_int(current_user.id),
            title=request.lessonplan_filename,
            user_type=session_segment,
        )
        await db.commit()

        logger.info(
            f"QnA 세션 생성: "
            f"session_id={session.id}, "
            f"user={_model_str(current_user.username)}, "
            f"file={request.lessonplan_filename}"
        )

        return CreateSessionResponse(
            session_id=_model_int(session.id),
            user_id=_model_int(session.user_id),
            lessonplan_filename=request.lessonplan_filename,
            created_at=_model_datetime(session.created_at),
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
        from app.services.qna_service import QnAService

        qna_service = QnAService(db)

        # 질문 처리
        result = await qna_service.ask_question(
            session_id=session_id,
            question=request.question,
            user_id=_model_int(current_user.id),
            username=_model_str(current_user.username),
        )
        await db.commit()

        logger.info(
            f"QnA 질문 처리: "
            f"session_id={session_id}, "
            f"user={_model_str(current_user.username)}"
        )

        return AskQuestionResponse(
            session_id=session_id,
            question=result["question"],
            answer=result["answer"],
            latency_ms=result.get("latency_ms"),
            citations=result.get("citations"),
            criteria_notice=result.get("criteria_notice"),
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
    "/sessions",
    response_model=UserSessionListResponse,
    summary="내 QnA 세션 목록",
    description="현재 로그인한 사용자의 QnA 세션 목록을 조회합니다.",
)
async def list_my_sessions(
    limit: int = Query(
        SESSION_LIST_DEFAULT_LIMIT,
        ge=1,
        le=SESSION_LIST_MAX_LIMIT,
    ),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    내 QnA 세션 목록 조회

    Args:
        current_user: 현재 로그인한 사용자
        db: 데이터베이스 세션

    Returns:
        현재 사용자 소유 세션 목록
    """
    try:
        current_user_id = _model_int(current_user.id)
        stats_session = aliased(ChatSession)

        message_stats = (
            select(
                ChatMessage.session_id,
                func.count(ChatMessage.id).label("message_count"),
                func.max(ChatMessage.created_at).label("last_message_at"),
            )
            .join(stats_session, stats_session.id == ChatMessage.session_id)
            .where(stats_session.user_id == current_user_id)
            .group_by(ChatMessage.session_id)
            .subquery()
        )

        total_result = await db.execute(
            select(func.count(ChatSession.id)).where(
                ChatSession.user_id == current_user_id
            )
        )
        total_count = int(total_result.scalar_one() or 0)

        last_activity_at = func.coalesce(
            message_stats.c.last_message_at,
            ChatSession.updated_at,
        )

        result = await db.execute(
            select(
                ChatSession,
                func.coalesce(
                    message_stats.c.message_count,
                    0,
                ).label("message_count"),
                message_stats.c.last_message_at,
            )
            .outerjoin(
                message_stats,
                ChatSession.id == message_stats.c.session_id,
            )
            .where(ChatSession.user_id == current_user_id)
            .order_by(last_activity_at.desc(), ChatSession.id.desc())
            .offset(offset)
            .limit(limit)
        )

        sessions = [
            UserSessionItem(
                session_id=session.id,
                title=_model_optional_str(session.title),
                user_type=_model_optional_str(session.user_type),
                created_at=_model_datetime(session.created_at),
                updated_at=_model_datetime(session.updated_at),
                message_count=int(message_count or 0),
                last_message_at=last_message_at,
            )
            for session, message_count, last_message_at in result.all()
        ]

        return UserSessionListResponse(
            sessions=sessions,
            total_count=total_count,
            returned_count=len(sessions),
            limit=limit,
            offset=offset,
            has_more=_has_more(offset, len(sessions), total_count),
        )

    except Exception as e:
        logger.error(
            f"내 QnA 세션 목록 조회 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="세션 목록 조회 중 오류가 발생했습니다."
        )


@router.get(
    "/sessions/{session_id}/history",
    response_model=ChatHistoryResponse,
    summary="대화 히스토리 조회",
    description="세션의 대화 히스토리를 조회합니다.",
)
async def get_chat_history(
    session_id: int,
    limit: int = Query(
        CHAT_HISTORY_DEFAULT_LIMIT,
        ge=1,
        le=CHAT_HISTORY_MAX_LIMIT,
    ),
    offset: int = Query(0, ge=0),
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
        session_result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == _model_int(current_user.id),
            )
        )
        if session_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="세션을 찾을 수 없습니다."
            )

        total_result = await db.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.session_id == session_id
            )
        )
        total_count = int(total_result.scalar_one() or 0)

        message_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .offset(offset)
            .limit(limit)
        )
        messages = message_result.scalars().all()

        # 응답 모델로 변환
        message_responses = [
            ChatMessageResponse(
                id=_model_int(msg.id),
                session_id=_model_int(msg.session_id),
                role=(
                    _model_str(msg.role.value)
                    if hasattr(msg.role, "value")
                    else str(msg.role)
                ),
                content=_model_str(msg.content),
                created_at=_model_datetime(msg.created_at),
            )
            for msg in messages
        ]

        return ChatHistoryResponse(
            session_id=session_id,
            messages=message_responses,
            total_count=total_count,
            returned_count=len(message_responses),
            limit=limit,
            offset=offset,
            has_more=_has_more(offset, len(message_responses), total_count),
        )

    except HTTPException:
        raise
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
        from app.services.qna_service import QnAService

        qna_service = QnAService(db)

        # 1. 해당 문서에 대한 기존 세션 찾기
        # title에 document_id를 저장한다고 가정
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.user_id == _model_int(current_user.id),
                ChatSession.title == document_id
            ).order_by(ChatSession.updated_at.desc()).limit(1)
        )
        session = result.scalar_one_or_none()

        # 2. 세션이 없으면 생성
        if not session:
            session_segment = await _session_segment_label_for_user(
                db, current_user
            )
            session = await qna_service.create_session(
                user_id=_model_int(current_user.id),
                title=document_id,
                user_type=session_segment,
            )
            await db.commit()
            logger.info(f"새 세션 자동 생성: {session.id} for {document_id}")

        # 3. 질문 처리
        # document_id 예:
        # fileSearchStores/user222store-j74m2v137dyv/documents/...
        # 여기서 store_id 추출:
        # fileSearchStores/user222store-j74m2v137dyv
        store_id = None
        if "fileSearchStores/" in document_id and "/documents/" in document_id:
            parts = document_id.split("/documents/")
            store_id = parts[0]

        result = await qna_service.ask_question(
            session_id=_model_int(session.id),
            question=request.question,
            user_id=_model_int(current_user.id),
            username=_model_str(current_user.username),
            store_id=store_id,
        )
        await db.commit()

        return AskQuestionResponse(
            session_id=_model_int(session.id),
            question=result["question"],
            answer=result["answer"],
            latency_ms=result.get("latency_ms"),
            citations=result.get("citations"),
            criteria_notice=result.get("criteria_notice"),
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
