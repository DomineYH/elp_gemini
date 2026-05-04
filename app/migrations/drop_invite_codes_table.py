"""
레거시 초대 코드 테이블 제거 마이그레이션 도우미
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _invite_codes_table_exists(sync_conn) -> bool:
    inspector = inspect(sync_conn)
    table_names = set(inspector.get_table_names())
    return "invite_codes" in table_names


async def drop_invite_codes_table(engine: AsyncEngine) -> bool:
    """
    레거시 invite_codes 테이블을 제거한다.

    Returns:
        테이블이 존재해 제거했으면 True, 이미 없으면 False
    """
    async with engine.begin() as conn:
        exists = await conn.run_sync(_invite_codes_table_exists)

        if not exists:
            logger.debug(
                "invite_codes 테이블이 없어 제거 마이그레이션을 건너뜀"
            )
            return False

        await conn.execute(text("DROP TABLE IF EXISTS invite_codes"))
        logger.info("invite_codes 테이블 제거 완료")
        return True
