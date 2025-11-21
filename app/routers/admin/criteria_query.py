"""
평가 기준 조회 라우터
관리자 전용 기준 문서 조회
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.users import User
from app.models.criteria import (
    CriteriaListResponse,
    CriteriaDetailResponse,
)
from app.repositories.criteria_repository import (
    CriteriaRepository,
)
from app.routers.auth import get_current_admin

router = APIRouter(tags=["admin", "criteria"])
logger = logging.getLogger(__name__)


@router.get("/", response_model=CriteriaListResponse)
async def list_criteria(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """평가 기준 문서 목록 조회"""
    try:
        # 페이지 크기 제한
        page_size = min(page_size, 100)

        repo = CriteriaRepository(db)
        documents, total = await repo.list_all(page, page_size)

        return CriteriaListResponse(
            items=[
                CriteriaDetailResponse.model_validate(doc)
                for doc in documents
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    except Exception as e:
        logger.error(f"목록 조회 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="목록을 불러올 수 없습니다"
        )


@router.get("/{criteria_id}", response_model=CriteriaDetailResponse)
async def get_criteria(
    criteria_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """평가 기준 문서 상세 조회"""
    try:
        repo = CriteriaRepository(db)
        document = await repo.get_by_id(criteria_id)

        if not document:
            raise HTTPException(
                status_code=404, detail="문서를 찾을 수 없습니다"
            )

        return CriteriaDetailResponse.model_validate(document)

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"문서 조회 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="문서를 불러올 수 없습니다"
        )
