"""
users.session_version 컬럼 보정 (#169)

서명 쿠키 세션은 서버가 무효화할 상태가 없으므로, 세션에 로그인 시점의
session_version을 저장하고 요청마다 DB 값과 비교한다. 로그아웃·관리자
비밀번호 변경 시 값을 올리면 이전 쿠키가 거부된다.
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


async def ensure_users_session_version_column(engine: AsyncEngine) -> bool:
    """`users.session_version` 컬럼이 없으면 추가한다."""
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_users_columns)
        if columns is None:
            logger.warning("users 테이블이 없어 session_version 패치를 건너뜀")
            return False
        if "session_version" in columns:
            return False
        await conn.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0"
            )
        )
        logger.info("users.session_version 컬럼 추가")
        return True
