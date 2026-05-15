"""
평가기준 스키마 보정 도우미
"""
from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _collect_criteria_columns(
    sync_conn,
) -> Optional[Set[str]]:
    """
    criteria 테이블의 컬럼명을 수집
    """
    inspector = inspect(sync_conn)

    try:
        columns = inspector.get_columns("criteria")
    except NoSuchTableError:
        return None

    return {col["name"] for col in columns}


async def ensure_criteria_file_path_column(
    engine: AsyncEngine,
    default_value: str = "legacy_missing",
) -> bool:
    """
    criteria.file_path 컬럼이 없을 경우 추가

    Args:
        engine: AsyncEngine 인스턴스
        default_value: 새 컬럼의 기본값

    Returns:
        컬럼이 새로 추가되었으면 True, 이미 존재하면 False
    """
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_criteria_columns)

        if columns is None:
            logger.warning(
                "criteria 테이블이 없어 스키마 패치를 건너뜀"
            )
            return False

        if "file_path" in columns:
            logger.debug(
                "criteria.file_path 컬럼이 이미 존재하여 패치를 건너뜀"
            )
            return False

        safe_default = default_value.replace("'", "''")
        await conn.execute(
            text(
                "ALTER TABLE criteria "
                "ADD COLUMN file_path VARCHAR(500) NOT NULL "
                f"DEFAULT '{safe_default}'"
            )
        )

        await conn.execute(
            text(
                "UPDATE criteria SET file_path = :default_value "
                "WHERE file_path IS NULL OR file_path = ''"
            ),
            {"default_value": default_value},
        )

        logger.info(
            "criteria.file_path 컬럼을 추가하고 기본값을 설정함"
        )
        return True


async def ensure_criteria_display_alias_column(
    engine: AsyncEngine,
) -> bool:
    """
    criteria.display_alias 컬럼이 없을 경우 추가.
    Returns True 컬럼이 새로 추가됨, False 이미 존재하거나 테이블 없음.
    """
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_criteria_columns)
        if columns is None:
            logger.warning(
                "criteria 테이블이 없어 display_alias 패치를 건너뜀"
            )
            return False
        if "display_alias" in columns:
            logger.debug(
                "criteria.display_alias 컬럼이 이미 존재하여 패치를 건너뜀"
            )
            return False

        await conn.execute(
            text(
                "ALTER TABLE criteria "
                "ADD COLUMN display_alias VARCHAR(255) NULL"
            )
        )
        logger.info("criteria.display_alias 컬럼을 추가함")
        return True


async def ensure_app_state_table(engine: AsyncEngine) -> bool:
    """app_state 테이블이 없을 경우 생성.

    Returns True 테이블이 새로 생성됨, False 이미 존재.
    """
    async with engine.begin() as conn:

        def _has_table(sync_conn) -> bool:
            from sqlalchemy import inspect

            return inspect(sync_conn).has_table("app_state")

        if await conn.run_sync(_has_table):
            logger.debug("app_state 테이블이 이미 존재하여 생성을 건너뜀")
            return False

        await conn.execute(
            text(
                "CREATE TABLE app_state ("
                "key VARCHAR(64) PRIMARY KEY, "
                "value TEXT NOT NULL, "
                "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        logger.info("app_state 테이블 생성 완료")
        return True

