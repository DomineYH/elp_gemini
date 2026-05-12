"""
chat_sessions.user_type 라벨 정규화: '현직교사' → '교사'
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def rename_chat_session_in_service_teacher_label(
    engine: AsyncEngine,
) -> int:
    """
    chat_sessions.user_type의 '현직교사' 레코드를 '교사'로 일괄 갱신.

    Returns:
        갱신된 행 수. 멱등이므로 두 번째 호출부터는 0.
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE chat_sessions "
                "SET user_type = '교사' "
                "WHERE user_type = '현직교사'"
            )
        )
        updated = result.rowcount or 0
        if updated:
            logger.info(
                "chat_sessions.user_type '현직교사' → '교사' 갱신 행 수: %d",
                updated,
            )
        return updated
