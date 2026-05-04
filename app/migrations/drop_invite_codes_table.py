"""
레거시 초대 코드 테이블 제거 마이그레이션 도우미
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _collect_invite_codes_table_state(sync_conn) -> tuple[bool, int | None]:
    inspector = inspect(sync_conn)
    table_names = set(inspector.get_table_names())
    if "invite_codes" not in table_names:
        return False, None

    try:
        row_count = sync_conn.execute(
            text("SELECT COUNT(*) FROM invite_codes")
        ).scalar_one()
    except Exception as exc:
        logger.warning(
            "invite_codes row count 확인 실패: %s", type(exc).__name__
        )
        row_count = None

    return True, int(row_count) if row_count is not None else None


async def drop_invite_codes_table(engine: AsyncEngine) -> bool:
    """
    레거시 invite_codes 테이블을 제거한다.

    Returns:
        테이블이 존재해 제거했으면 True, 이미 없으면 False
    """
    async with engine.begin() as conn:
        exists, row_count = await conn.run_sync(
            _collect_invite_codes_table_state
        )

        if not exists:
            logger.debug(
                "invite_codes 테이블이 없어 제거 마이그레이션을 건너뜀"
            )
            return False

        if row_count is None:
            logger.warning(
                "invite_codes 테이블 row count 확인 없이 삭제를 진행"
            )
        else:
            logger.info(
                "invite_codes 테이블 삭제 진행: rows=%s", row_count
            )

        await conn.execute(text("DROP TABLE IF EXISTS invite_codes"))
        logger.info("invite_codes 테이블 제거 완료")
        return True
