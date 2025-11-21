"""
평가 기준 관리 통합 라우터
모든 하위 라우터를 통합
"""
from fastapi import APIRouter

from . import (
    criteria_upload,
    criteria_activation,
    criteria_query,
    criteria_views,
    criteria_delete,
)

router = APIRouter(
    prefix="/admin/criteria", tags=["admin", "criteria"]
)

# 하위 라우터 통합
# HTML 뷰를 먼저 등록하여 경로 우선순위 확보
router.include_router(criteria_views.router)
router.include_router(criteria_upload.router)
router.include_router(criteria_activation.router)
router.include_router(criteria_query.router)
router.include_router(criteria_delete.router)
