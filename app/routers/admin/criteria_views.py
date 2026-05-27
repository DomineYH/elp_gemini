"""
관리자 - 평가기준 관리 뷰 라우터
평가기준 목록, 업로드, 상세 페이지 렌더링
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
)
from app.repositories.criteria_repository import (
    CriteriaRepository
)
from app.services.criteria_freshness import ensure_criteria_cache_fresh

router = APIRouter(
    prefix="/admin/criteria",
    tags=["관리자-평가기준-뷰"]
)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")


async def _fetch_sync_metadata(db: AsyncSession) -> dict:
    """app_state에서 클라우드 동기화 상태를 읽어온다."""
    repo = AppStateRepository(db=db)
    return {
        "state": await repo.get(KEY_SYNC_STATE),
        "last_synced_at": await repo.get(KEY_LAST_SYNCED_AT),
        "error": await repo.get(KEY_SYNC_ERROR),
    }


def _criteria_items_from_rows(all_criteria) -> list[dict]:
    """Template context rows; pre-reconcile rows without stable_id are hidden."""
    from app.services.criteria_reconciliation_service import (
        is_legacy_surrogate_stable_id,
    )
    return [
        {
            "stable_id": c.stable_id,
            "title": c.title,
            "display_alias": c.display_alias,
            "status": c.status,
            "created_at": c.created_at,
            "document_id": c.document_id,
            "is_legacy": is_legacy_surrogate_stable_id(c.stable_id),
        }
        for c in all_criteria
        if c.stable_id is not None
    ]


@router.get(
    "",
    response_class=HTMLResponse,
    summary="평가기준 목록",
    description="평가기준 목록 페이지"
)
async def criteria_list(
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    _fresh=Depends(ensure_criteria_cache_fresh),
):
    """
    평가기준 목록 페이지

    Args:
        request: FastAPI Request 객체
        current_admin: 현재 로그인한 관리자

    Returns:
        평가기준 목록 HTML 페이지
    """
    logger.info(f"평가기준 목록 접근: admin={current_admin.username}")

    try:
        criteria_repo = CriteriaRepository(db)
        all_criteria = await criteria_repo.get_all_criteria()

        criteria_items = _criteria_items_from_rows(all_criteria)

        sync = await _fetch_sync_metadata(db)

        return templates.TemplateResponse(
            "admin/criteria_list.html",
            {
                "request": request,
                "user": current_admin,
                "criteria_items": criteria_items,
                "sync": sync,
            }
        )
    except Exception as e:
        logger.error(f"평가기준 목록 조회 실패: {str(e)}", exc_info=True)
        # 오류 발생 시 빈 목록 표시
        return templates.TemplateResponse(
            "admin/criteria_list.html",
            {
                "request": request,
                "user": current_admin,
                "criteria_items": [],
                "sync": {"state": None, "last_synced_at": None, "error": None},
            }
        )


@router.get(
    "/upload",
    response_class=HTMLResponse,
    summary="평가기준 업로드 페이지",
    description="평가기준 업로드 페이지"
)
async def criteria_upload_page(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    """
    평가기준 업로드 페이지

    Args:
        request: FastAPI Request 객체
        current_admin: 현재 로그인한 관리자

    Returns:
        평가기준 업로드 HTML 페이지
    """
    logger.info(f"평가기준 업로드 페이지 접근: admin={current_admin.username}")

    return templates.TemplateResponse(
        "admin/criteria_upload.html",
        {
            "request": request,
            "user": current_admin,
        }
    )


@router.get(
    "/{criteria_id}",
    response_class=HTMLResponse,
    summary="평가기준 상세",
    description="평가기준 상세 페이지"
)
async def criteria_detail(
    criteria_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    평가기준 상세 페이지

    Args:
        criteria_id: 평가기준 ID
        request: FastAPI Request 객체
        current_admin: 현재 로그인한 관리자

    Returns:
        평가기준 상세 HTML 페이지
    """
    logger.info(
        f"평가기준 상세 접근: admin={current_admin.username}, "
        f"criteria_id={criteria_id}"
    )

    try:
        # DB에서 평가기준 데이터 조회
        criteria_repo = CriteriaRepository(db)
        criteria = await criteria_repo.get_criteria_by_id(
            criteria_id
        )

        if not criteria:
            logger.warning(
                f"평가기준 없음: id={criteria_id}"
            )
            raise HTTPException(
                status_code=404,
                detail="평가기준을 찾을 수 없습니다."
            )

        return templates.TemplateResponse(
            "admin/criteria_detail.html",
            {
                "request": request,
                "user": current_admin,
                "criteria": criteria,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"평가기준 상세 조회 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="평가기준 조회 중 오류가 발생했습니다."
        )
