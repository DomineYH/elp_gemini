"""
관리자 대시보드 라우터
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.services.cloud_sync_validator import CloudSyncValidator

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
    db: AsyncSession = Depends(get_db),
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

    metrics = {
        "total_users": 0,
        "total_documents": 0,
        "documents_last_7days": 0,
        "total_qna_logs": 0,
        "qna_logs_last_7days": 0,
        "total_evaluation_runs": 0,
        "evaluation_runs_last_7days": 0,
    }

    sync_warning = None
    try:
        validator = CloudSyncValidator()
        sync_result = await validator.validate_rubricstore_sync(db)
        if sync_result.needs_resync:
            sync_warning = sync_result.warning_message
            logger.warning(f"클라우드 동기화 경고: {sync_warning}")
    except Exception as e:
        logger.error(f"동기화 검증 실패: {e}")
        sync_warning = f"클라우드 연결 확인 실패: {str(e)}"

    return templates.TemplateResponse(
        "admin/admin_dashboard.html",
        {
            "request": request,
            "user": current_admin,
            "metrics": metrics,
            "sync_warning": sync_warning,
        }
    )
