"""
관리자 대시보드 라우터
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import logging

from app.dependencies import get_current_admin
from app.models.users import User

router = APIRouter(
    prefix="/admin",
    tags=["관리자-대시보드"]
)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="관리자 대시보드",
    description="관리자 대시보드 페이지"
)
async def admin_dashboard(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    """
    관리자 대시보드

    Args:
        request: FastAPI Request 객체
        current_admin: 현재 로그인한 관리자

    Returns:
        관리자 대시보드 HTML 페이지
    """
    logger.info(f"관리자 대시보드 접근: admin={current_admin.username}")

    # TODO: 실제 통계 데이터 조회 로직 구현 필요
    # 현재는 임시로 0 값으로 초기화
    metrics = {
        "total_users": 0,
        "total_documents": 0,
        "documents_last_7days": 0,
        "total_qna_logs": 0,
        "qna_logs_last_7days": 0,
        "total_evaluation_runs": 0,
        "evaluation_runs_last_7days": 0,
    }

    return templates.TemplateResponse(
        "admin/admin_dashboard.html",
        {
            "request": request,
            "user": current_admin,
            "metrics": metrics,
        }
    )
