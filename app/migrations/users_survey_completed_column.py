"""
설문 게이트용 users 테이블 컬럼 보정

추가 컬럼:
- survey_completed_at: 참여 설문 완료 시각 (NULL=미완료)
"""
from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _collect_users_columns(sync_conn) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        columns = inspector.get_columns("users")
    except NoSuchTableError:
        return None
    return {col["name"] for col in columns}


async def ensure_users_survey_completed_column(engine: AsyncEngine) -> bool:
    """
    users 테이블에 survey_completed_at 컬럼 추가

    Returns:
        새 컬럼을 추가하면 True, 이미 있으면 False
    """
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_users_columns)

        if columns is None:
            logger.warning(
                "users 테이블이 없어 survey_completed_at 패치를 건너뜀"
            )
            return False

        if "survey_completed_at" in columns:
            return False

        await conn.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN survey_completed_at DATETIME"
            )
        )
        logger.info("users.survey_completed_at 컬럼 추가")
        return True
