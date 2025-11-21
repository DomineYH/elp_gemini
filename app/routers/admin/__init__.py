"""
Admin 라우터 패키지
"""
from . import core, criteria

router = core.router
router.include_router(criteria.router)
