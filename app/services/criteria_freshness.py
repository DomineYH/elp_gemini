"""
Issue #80 — 평가기준 목록 endpoint에서 cloud freshness를 lazy하게 확인.

list 호출 시점에 in-process throttle을 거쳐 reconcile()을 호출한다. cloud의
alias_map.updated_at이 안 바뀌었다면 reconcile은 Task 2 가드로 빠르게 skip된다.
다른 인스턴스가 cloud를 갱신했다면 local cache가 자동으로 따라잡는다.

원칙:
- cloud 호출 실패는 사용자 경로를 끊지 않는다 (로그만 남기고 무시).
- CRITERIA_CLOUD_RECONCILE_ENABLED=False 시 dependency는 no-op.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

logger = logging.getLogger(__name__)

_throttle_lock = asyncio.Lock()
_last_check_monotonic: Optional[float] = None


def _reset_throttle_for_test() -> None:
    """테스트 전용 — throttle 상태 초기화."""
    global _last_check_monotonic
    _last_check_monotonic = None


async def _run_reconcile_once(db: AsyncSession) -> None:
    """주어진 request-scoped 세션에서 reconcile을 1회 실행."""
    from app.repositories.app_state_repository import AppStateRepository
    from app.repositories.criteria_repository import CriteriaRepository
    from app.services.criteria_alias_map_service import (
        CriteriaAliasMapService,
    )
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )
    from app.services.criteria_vector_service import CriteriaVectorService

    vec = CriteriaVectorService()
    alias = CriteriaAliasMapService(
        client=vec.file_search_service.client,
        store_display_name=settings.FS_RUBRIC_STORE_NAME,
    )
    svc = CriteriaReconciliationService(
        db=db,
        vector_service=vec,
        alias_map_service=alias,
        criteria_repo=CriteriaRepository(db=db),
        app_state_repo=AppStateRepository(db=db),
    )
    await svc.reconcile(swallow_errors=True)


async def ensure_criteria_cache_fresh(
    db: AsyncSession = Depends(get_db),
) -> None:
    """FastAPI Depends() 대상 — list endpoint 진입 시 호출."""
    global _last_check_monotonic

    if not settings.CRITERIA_CLOUD_RECONCILE_ENABLED:
        return

    ttl = settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS
    now = time.monotonic()

    async with _throttle_lock:
        if (
            _last_check_monotonic is not None
            and ttl > 0
            and (now - _last_check_monotonic) < ttl
        ):
            return
        _last_check_monotonic = now

    try:
        await _run_reconcile_once(db)
    except Exception:
        logger.warning(
            "평가기준 freshness 확인 실패 (cache 그대로 응답)",
            exc_info=True,
        )
