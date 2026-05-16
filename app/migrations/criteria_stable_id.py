"""
criteria.stable_id 컬럼 추가 마이그레이션

클라우드 진실의 원천 모델에서 평가기준 식별자.
NULL 허용으로 시작 — 첫 reconcile이 백필.
"""
from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import inspect
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _collect_columns(sync_conn) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        columns = inspector.get_columns("criteria")
    except NoSuchTableError:
        return None
    return {col["name"] for col in columns}


async def ensure_criteria_stable_id_column(engine: AsyncEngine) -> bool:
    """`criteria.stable_id` 컬럼이 없으면 추가한다."""
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_columns)
        if columns is None:
            logger.warning("criteria 테이블이 없어 stable_id 패치를 건너뜀")
            return False
        column_added = False
        if "stable_id" in columns:
            logger.debug("criteria.stable_id 컬럼이 이미 존재함")
        else:
            await conn.execute(text(
                "ALTER TABLE criteria ADD COLUMN stable_id VARCHAR(64) NULL"
            ))
            logger.info("criteria.stable_id 컬럼을 추가함")
            column_added = True
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_criteria_stable_id "
            "ON criteria(stable_id)"
        ))
        return column_added
