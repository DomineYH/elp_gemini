"""
관리자 QnA 로그 라우터
세션 기반 대화 로그 조회 API
"""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
import logging

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.models.chat_sessions import ChatSession
from app.models.chat_messages import ChatMessage
from app.utils.admin_csrf import ensure_admin_csrf_token

router = APIRouter(tags=["관리자-QnA로그"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


@router.get("/admin/api/qna-logs")
async def get_qna_logs(
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    user_type: str = Query(None, description="사용자 유형 필터"),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 QnA 로그 조회 API

    세션 단위로 묶인 대화 내용을 조회합니다.
    각 세션에는 user_type, session_id, 메시지 목록이 포함됩니다.

    Args:
        page: 페이지 번호 (1부터 시작)
        page_size: 페이지당 세션 수
        user_type: 사용자 유형 필터 (1학년, 2학년, 3학년, 4학년, 교사)

    Returns:
        세션 목록과 페이징 정보
    """
    try:
        # 기본 쿼리: 세션과 메시지를 함께 로드
        query = (
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .order_by(ChatSession.created_at.desc())
        )

        # user_type 필터 적용
        if user_type:
            query = query.where(ChatSession.user_type == user_type)

        # 전체 개수 조회
        count_query = select(func.count()).select_from(ChatSession)
        if user_type:
            count_query = count_query.where(ChatSession.user_type == user_type)
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # 페이징 적용
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        # 세션 조회
        result = await db.execute(query)
        sessions = result.scalars().all()

        # 응답 구성
        sessions_data = []
        for session in sessions:
            # 메시지를 시간순 정렬
            sorted_messages = sorted(
                session.messages, key=lambda m: m.created_at
            )

            messages_data = [
                {
                    "id": msg.id,
                    "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in sorted_messages
            ]

            sessions_data.append({
                "session_id": session.id,
                "user_type": session.user_type,
                "title": session.title,
                "messages": messages_data,
                "message_count": len(messages_data),
                "created_at": session.created_at.isoformat(),
            })

        logger.info(
            f"QnA 로그 조회: admin={current_admin.username}, "
            f"page={page}, total={total}, user_type={user_type}"
        )

        return {
            "sessions": sessions_data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    except Exception as e:
        logger.error(f"QnA 로그 조회 실패: {str(e)}", exc_info=True)
        raise


@router.get("/admin/qna-logs", response_class=HTMLResponse)
async def qna_logs_page(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    """
    QnA 로그 페이지 렌더링

    세션 삭제 작업을 위해 CSRF 토큰을 함께 주입한다.
    """
    csrf_token = ensure_admin_csrf_token(request)
    return templates.TemplateResponse(
        "admin/admin_qna_logs.html",
        {
            "request": request,
            "user": current_admin,
            "csrf_token": csrf_token,
        },
    )
