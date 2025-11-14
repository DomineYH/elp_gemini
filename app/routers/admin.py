"""
관리자 라우터
대시보드, 사용자 관리, QnA 로그, 시스템 프롬프트 관리
"""
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.users import User
from app.schemas.admin import (
    AdminDashboardResponse,
    AdminUserResponse,
    AdminUserDetailResponse,
    AdminQALogResponse,
)
from app.schemas.prompts import (
    SystemPromptResponse,
    SystemPromptCreateRequest,
)
from app.routers.auth import get_current_admin
from app.services.admin_service import AdminService
from app.utils.logging import log_user_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


# T096: GET /admin/dashboard - 대시보드 메트릭
@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 대시보드 (HTML)
    """
    try:
        admin_service = AdminService(db)
        metrics = await admin_service.get_dashboard_metrics()

        log_user_action(
            current_user.id, "view_admin_dashboard", {}
        )

        return templates.TemplateResponse(
            "admin/admin_dashboard.html",
            {
                "request": request,
                "user": current_user,
                "metrics": metrics,
            },
        )

    except Exception as e:
        logger.error(f"대시보드 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="대시보드를 불러올 수 없습니다"
        )


@router.get("/api/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard_metrics(
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 대시보드 메트릭 (API)
    """
    try:
        admin_service = AdminService(db)
        metrics = await admin_service.get_dashboard_metrics()

        log_user_action(
            current_user.id, "get_dashboard_metrics", {}
        )

        return AdminDashboardResponse(**metrics)

    except Exception as e:
        logger.error(f"메트릭 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="메트릭을 불러올 수 없습니다"
        )


# T097: GET /admin/users - 사용자 목록
@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 사용자 목록 (HTML)
    """
    try:
        admin_service = AdminService(db)
        users = await admin_service.get_users_with_activity()

        log_user_action(
            current_user.id, "view_admin_users", {}
        )

        return templates.TemplateResponse(
            "admin/admin_users.html",
            {
                "request": request,
                "user": current_user,
                "users": users,
            },
        )

    except Exception as e:
        logger.error(f"사용자 목록 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="사용자 목록을 불러올 수 없습니다"
        )


@router.get("/api/users", response_model=List[AdminUserResponse])
async def get_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 사용자 목록 (API)
    """
    try:
        admin_service = AdminService(db)
        offset = (page - 1) * page_size
        users = await admin_service.get_users_with_activity(
            limit=page_size, offset=offset
        )

        return [AdminUserResponse(**user) for user in users]

    except Exception as e:
        logger.error(f"사용자 목록 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="사용자 목록을 불러올 수 없습니다"
        )


# T098: GET /admin/users/{user_id} - 사용자 상세
@router.get("/users/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 사용자 상세 (HTML)
    """
    try:
        admin_service = AdminService(db)
        user_detail = await admin_service.get_user_detail(user_id)

        if not user_detail:
            raise HTTPException(
                status_code=404, detail="사용자를 찾을 수 없습니다"
            )

        log_user_action(
            current_user.id,
            "view_user_detail",
            {"target_user_id": user_id},
        )

        return templates.TemplateResponse(
            "admin/admin_user_detail.html",
            {
                "request": request,
                "user": current_user,
                "target_user": user_detail,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"사용자 상세 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="사용자 정보를 불러올 수 없습니다"
        )


@router.get(
    "/api/users/{user_id}",
    response_model=AdminUserDetailResponse,
)
async def get_user_detail(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 사용자 상세 (API)
    """
    try:
        admin_service = AdminService(db)
        user_detail = await admin_service.get_user_detail(user_id)

        if not user_detail:
            raise HTTPException(
                status_code=404, detail="사용자를 찾을 수 없습니다"
            )

        return AdminUserDetailResponse(**user_detail)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"사용자 상세 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="사용자 정보를 불러올 수 없습니다"
        )


# T099: GET /admin/qna-logs - QnA 로그
@router.get("/qna-logs", response_class=HTMLResponse)
async def admin_qna_logs(
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 QnA 로그 (HTML)
    """
    try:
        log_user_action(
            current_user.id, "view_qna_logs", {}
        )

        return templates.TemplateResponse(
            "admin/admin_qna_logs.html",
            {
                "request": request,
                "user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"QnA 로그 페이지 로드 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="QnA 로그를 불러올 수 없습니다"
        )


@router.get("/api/qna-logs", response_model=List[AdminQALogResponse])
async def get_qna_logs(
    user_id: Optional[int] = Query(None),
    document_id: Optional[int] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 QnA 로그 필터링 (API)
    """
    try:
        admin_service = AdminService(db)
        offset = (page - 1) * page_size

        logs = await admin_service.get_qna_logs(
            user_id=user_id,
            document_id=document_id,
            start_date=start_date,
            end_date=end_date,
            limit=page_size,
            offset=offset,
        )

        return [AdminQALogResponse(**log) for log in logs]

    except Exception as e:
        logger.error(f"QnA 로그 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="QnA 로그를 불러올 수 없습니다"
        )


# T100: GET /admin/prompts - 시스템 프롬프트 목록
@router.get("/prompts", response_class=HTMLResponse)
async def admin_prompts(
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 프롬프트 관리 (HTML)
    """
    try:
        admin_service = AdminService(db)
        prompts = await admin_service.get_system_prompts()

        log_user_action(
            current_user.id, "view_prompts", {}
        )

        return templates.TemplateResponse(
            "admin/admin_prompts.html",
            {
                "request": request,
                "user": current_user,
                "prompts": prompts,
            },
        )

    except Exception as e:
        logger.error(f"프롬프트 페이지 로드 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="프롬프트 목록을 불러올 수 없습니다"
        )


@router.get("/api/prompts", response_model=List[SystemPromptResponse])
async def get_prompts(
    prompt_type: Optional[str] = Query(None),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 시스템 프롬프트 목록 (API)
    """
    try:
        admin_service = AdminService(db)
        prompts = await admin_service.get_system_prompts(
            prompt_type=prompt_type
        )

        return [
            SystemPromptResponse.model_validate(prompt)
            for prompt in prompts
        ]

    except Exception as e:
        logger.error(f"프롬프트 목록 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="프롬프트 목록을 불러올 수 없습니다"
        )


# T101: POST /admin/prompts - 프롬프트 생성
@router.post("/api/prompts", response_model=SystemPromptResponse)
async def create_prompt(
    request: SystemPromptCreateRequest,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    새 시스템 프롬프트 생성
    """
    try:
        admin_service = AdminService(db)
        prompt = await admin_service.create_system_prompt(
            prompt_type=request.type,
            content=request.content,
            created_by=current_user.id,
        )

        log_user_action(
            current_user.id,
            "create_prompt",
            {"prompt_id": prompt.id, "type": prompt.type},
        )

        return SystemPromptResponse.model_validate(prompt)

    except Exception as e:
        logger.error(f"프롬프트 생성 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="프롬프트 생성 중 오류가 발생했습니다"
        )


# T102: POST /admin/prompts/{prompt_id}/activate - 프롬프트 활성화
@router.post(
    "/api/prompts/{prompt_id}/activate",
    response_model=SystemPromptResponse,
)
async def activate_prompt(
    prompt_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    시스템 프롬프트 활성화
    """
    try:
        admin_service = AdminService(db)
        prompt = await admin_service.activate_system_prompt(
            prompt_id
        )

        log_user_action(
            current_user.id,
            "activate_prompt",
            {"prompt_id": prompt.id, "type": prompt.type},
        )

        return SystemPromptResponse.model_validate(prompt)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"프롬프트 활성화 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="프롬프트 활성화 중 오류가 발생했습니다"
        )
