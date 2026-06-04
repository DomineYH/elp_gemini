"""
레거시 user_profiles 테이블 제거 마이그레이션 도우미
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def drop_user_profiles(engine: AsyncEngine) -> bool:
    """
    user_profiles 테이블을 제거한다.

    Returns:
        테이블이 존재해 제거했으면 True, 이미 없으면 False
    """
    async with engine.begin() as conn:
        exists = await conn.run_sync(
            lambda sync_conn: "user_profiles"
            in set(inspect(sync_conn).get_table_names())
        )

        if not exists:
            logger.debug(
                "user_profiles 테이블이 없어 제거 마이그레이션을 건너뜀"
            )
            return False

        logger.info("user_profiles 테이블 삭제 진행")
        await conn.execute(text("DROP TABLE IF EXISTS user_profiles"))
        logger.info("user_profiles 테이블 제거 완료")
        return True
