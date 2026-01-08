"""
Admin 라우터 패키지
"""
from fastapi import APIRouter
from . import criteria, criteria_views, dashboard, qna_logs

# 메인 admin 라우터 생성
router = APIRouter()

# 각 서브 라우터 포함
router.include_router(dashboard.router)
router.include_router(criteria_views.router)  # 뷰 라우터 먼저 등록
router.include_router(criteria.router)  # API 라우터는 나중에 등록
router.include_router(qna_logs.router)  # QnA 로그 라우터
