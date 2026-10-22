"""
관리자 대시보드 라우터
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.analysis_reports import AnalysisReport
from app.models.chat_sessions import ChatSession
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_session import SimulationSession
from app.models.users import User
from app.templating import templates

router = APIRouter(prefix="/admin", tags=["관리자-대시보드"])
logger = logging.getLogger(__name__)

# (키, 라벨, 모델) — 전체 수와 최근 7일 수를 함께 보인다 (#181)
_ACTIVITY_METRICS = (
    ("uploads", "지도안 업로드", LessonPlanUpload),
    ("reports", "분석 보고서", AnalysisReport),
    ("qna_sessions", "QnA 세션", ChatSession),
    ("simulations", "시뮬레이션 세션", SimulationSession),
)


async def _collect_metrics(db: AsyncSession) -> dict:
    # created_at(CURRENT_TIMESTAMP)과 같은 UTC naive 기준
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    users = await db.scalar(
        select(func.count(User.id)).where(User.is_admin.is_(False))
    )
    activity = []
    for key, label, model in _ACTIVITY_METRICS:
        total = await db.scalar(select(func.count(model.id)))
        recent = await db.scalar(
            select(func.count(model.id)).where(model.created_at >= since)
        )
        activity.append(
            {
                "key": key,
                "label": label,
                "total": total or 0,
                "last_7days": recent or 0,
            }
        )
    return {"total_users": users or 0, "activity": activity}


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="관리자 대시보드",
    description="관리자 대시보드 페이지",
)
async def admin_dashboard(
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 대시보드

    Args:
        request: FastAPI Request 객체
        current_admin: 현재 로그인한 관리자
        db: 데이터베이스 세션

    Returns:
        관리자 대시보드 HTML 페이지
    """
    logger.info(f"관리자 대시보드 접근: admin={current_admin.username}")

    metrics = await _collect_metrics(db)

    return templates.TemplateResponse(
        "admin/admin_dashboard.html",
        {
            "request": request,
            "user": current_admin,
            "metrics": metrics,
        },
    )
