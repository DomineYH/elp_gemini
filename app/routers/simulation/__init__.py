"""
수업 시뮬레이션 라우터 패키지
"""

from fastapi import APIRouter

from . import core, feedback, library

router = APIRouter()

router.include_router(core.router)
router.include_router(feedback.router)
router.include_router(library.router)
