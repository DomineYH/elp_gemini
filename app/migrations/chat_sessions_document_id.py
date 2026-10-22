"""
chat_sessions.document_id 컬럼 추가 마이그레이션 (#175)

문서 대화 세션의 키를 title에서 분리한다. 과거 행은 title에 File Search
문서 경로를 저장했으므로 그 값을 document_id로 백필해 세션 재사용을 유지한다.
백필 뒤 그 title은 업로드 파일명이나 고정 문구로 바꾼다 (#214).
"""

from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _collect_columns(sync_conn) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        columns = inspector.get_columns("chat_sessions")
    except NoSuchTableError:
        return None
    return {col["name"] for col in columns}


async def ensure_chat_sessions_document_id_column(engine: AsyncEngine) -> bool:
    """`chat_sessions.document_id` 컬럼이 없으면 추가하고 과거 행을 백필한다."""
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_columns)
        if columns is None:
            logger.warning(
                "chat_sessions 테이블이 없어 document_id 패치를 건너뜀"
            )
            return False
        column_added = False
        if "document_id" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE chat_sessions "
                    "ADD COLUMN document_id VARCHAR(512) NULL"
                )
            )
            logger.info("chat_sessions.document_id 컬럼을 추가함")
            column_added = True
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_chat_sessions_document_id "
                "ON chat_sessions(document_id)"
            )
        )
        result = await conn.execute(
            text(
                "UPDATE chat_sessions SET document_id = title "
                "WHERE document_id IS NULL AND title LIKE 'fileSearchStores/%'"
            )
        )
        if result.rowcount:
            logger.info(
                "chat_sessions.document_id 백필: %d 행", result.rowcount
            )
        # document_id 백필 뒤에 실행해야 원래 문서 경로가 남는다
        result = await conn.execute(
            text(
                "UPDATE chat_sessions SET title = SUBSTR(COALESCE(("
                "SELECT u.original_filename FROM lessonplan_uploads u "
                "WHERE u.user_id = chat_sessions.user_id "
                "AND u.fs_document_id = chat_sessions.document_id "
                "AND u.original_filename IS NOT NULL "
                "AND u.original_filename != '' "
                "ORDER BY u.created_at DESC, u.id DESC LIMIT 1"
                "), '업로드한 지도안'), 1, 255) "
                "WHERE title LIKE 'fileSearchStores/%'"
            )
        )
        if result.rowcount:
            logger.info(
                "chat_sessions.title 레거시 제목 정리: %d 행", result.rowcount
            )
        return column_added
