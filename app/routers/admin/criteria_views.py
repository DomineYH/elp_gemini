"""
평가 기준 HTML 뷰 라우터
관리자 전용 HTML 페이지 렌더링
"""
import logging
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.users import User
from app.routers.auth import get_current_admin
from app.repositories.criteria_repository import (
    CriteriaRepository,
)

router = APIRouter(tags=["admin", "criteria"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


@router.get("/", response_class=HTMLResponse)
async def criteria_list_page(
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """평가 기준 목록 페이지 (HTML)"""
    try:
        repo = CriteriaRepository(db)

        # 전체 목록 조회 (페이지네이션 없이)
        documents, total = await repo.list_all(
            page=1, page_size=100
        )

        # 활성 기준 조회
        active_criteria = await repo.get_active()

        return templates.TemplateResponse(
            "admin/criteria_list.html",
            {
                "request": request,
                "user": current_user,
                "criteria": {
                    "documents": documents,
                    "total": total,
                },
                "active_criteria": active_criteria,
            },
        )

    except Exception as e:
        logger.error(
            f"목록 페이지 렌더링 실패: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="목록 페이지를 불러올 수 없습니다",
        )


@router.get("/upload", response_class=HTMLResponse)
async def criteria_upload_page(
    request: Request,
    current_user: User = Depends(get_current_admin),
):
    """평가 기준 업로드 페이지 (HTML)"""
    try:
        return templates.TemplateResponse(
            "admin/criteria_upload.html",
            {
                "request": request,
                "user": current_user,
            },
        )

    except Exception as e:
        logger.error(
            f"업로드 페이지 렌더링 실패: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="업로드 페이지를 불러올 수 없습니다",
        )


@router.get("/{criteria_id}", response_class=HTMLResponse)
async def criteria_detail_page(
    request: Request,
    criteria_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """평가 기준 상세 페이지 (HTML)"""
    try:
        repo = CriteriaRepository(db)
        criteria = await repo.get_by_id(criteria_id)

        if not criteria:
            raise HTTPException(
                status_code=404,
                detail="문서를 찾을 수 없습니다",
            )

        return templates.TemplateResponse(
            "admin/criteria_detail.html",
            {
                "request": request,
                "user": current_user,
                "criteria": criteria,
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"상세 페이지 렌더링 실패: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="상세 페이지를 불러올 수 없습니다",
        )
