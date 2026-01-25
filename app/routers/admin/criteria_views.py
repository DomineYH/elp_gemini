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
from app.repositories.criteria_repository import (
    CriteriaRepository
)
from app.services.cloud_sync_validator import CloudSyncValidator
from app.services.criteria_vector_service import CriteriaVectorService

router = APIRouter(
    prefix="/admin/criteria",
    tags=["관리자-평가기준-뷰"]
)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")


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
        # DB에서 평가기준 목록 조회
        criteria_repo = CriteriaRepository(db)
        all_criteria = await criteria_repo.get_all_criteria()

        # 클라우드 문서 목록 조회
        cloud_documents = []
        cloud_error = None
        try:
            criteria_service = CriteriaVectorService()
            cloud_documents = await criteria_service.list_criteria_documents()
        except Exception as e:
            logger.warning(f"클라우드 문서 목록 조회 실패: {e}")
            cloud_error = str(e)

        # document_id 매핑 생성 (DB ↔ 클라우드 연동 확인용)
        cloud_doc_ids = {doc["document_id"] for doc in cloud_documents}

        # 템플릿에 맞게 데이터 변환
        criteria_items = {
            "documents": [
                {
                    "id": criteria.id,
                    "title": criteria.title,
                    "status": criteria.status,
                    "file_size": criteria.file_size,
                    "created_at": criteria.created_at,
                    "document_id": criteria.document_id,
                    "cloud_synced": (
                        criteria.document_id is not None
                        and criteria.document_id in cloud_doc_ids
                    ),
                }
                for criteria in all_criteria
            ]
        }

        # 활성 기준 조회 (status='active'인 것)
        active_criteria = next(
            (
                c for c in all_criteria
                if c.status == "active"
            ),
            None
        )

        pending_sync_criteria = [
            c for c in all_criteria
            if c.status == "active" and (
                c.synced_at is None or c.synced_at < c.updated_at
            )
        ]
        needs_sync = len(pending_sync_criteria) > 0

        cloud_sync_warning = None
        try:
            validator = CloudSyncValidator()
            sync_result = await validator.validate_rubricstore_sync(db)
            if sync_result.needs_resync:
                cloud_sync_warning = sync_result.warning_message
        except Exception as e:
            logger.warning(f"클라우드 동기화 검증 실패: {e}")

        return templates.TemplateResponse(
            "admin/criteria_list.html",
            {
                "request": request,
                "user": current_admin,
                "criteria": criteria_items,
                "active_criteria": active_criteria,
                "needs_sync": needs_sync,
                "pending_count": len(pending_sync_criteria),
                "cloud_sync_warning": cloud_sync_warning,
                "cloud_documents": cloud_documents,
                "cloud_error": cloud_error,
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
                "criteria": {"documents": []},
                "active_criteria": None,
                "needs_sync": False,
                "pending_count": 0,
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
