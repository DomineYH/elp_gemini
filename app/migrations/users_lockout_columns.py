"""
관리자 brute-force 방어용 users 테이블 컬럼 보정

추가 컬럼:
- failed_login_count: 누적 실패 횟수
- locked_until: 잠금 만료 시각 (NULL=잠금 없음)
- last_failed_login_at: 마지막 실패 시각
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


async def ensure_users_lockout_columns(engine: AsyncEngine) -> bool:
    """
    users 테이블에 brute-force 방어용 컬럼 추가

    Returns:
        하나라도 새 컬럼을 추가하면 True, 모두 이미 있으면 False
    """
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_users_columns)

        if columns is None:
            logger.warning(
                "users 테이블이 없어 lockout 컬럼 패치를 건너뜀"
            )
            return False

        added = False

        if "failed_login_count" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN failed_login_count INTEGER "
                    "NOT NULL DEFAULT 0"
                )
            )
            added = True
            logger.info("users.failed_login_count 컬럼 추가")

        if "locked_until" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN locked_until DATETIME NULL"
                )
            )
            added = True
            logger.info("users.locked_until 컬럼 추가")

        if "last_failed_login_at" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN last_failed_login_at DATETIME NULL"
                )
            )
            added = True
            logger.info("users.last_failed_login_at 컬럼 추가")

        return added
