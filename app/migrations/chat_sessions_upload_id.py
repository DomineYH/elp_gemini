"""
chat_sessions.upload_id 컬럼 추가 (#290)

문서 대화 세션을 만든 시점의 지도안 업로드를 기록한다. 과거 행은 NULL로
남긴다(백필 없음). SQLite는 FK 컬럼을 DROP할 수 없으므로 되돌릴 때는 컬럼을
남겨 둔다(nullable이라 옛 코드는 무시한다).
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


async def ensure_chat_sessions_upload_id_column(engine: AsyncEngine) -> bool:
    """`chat_sessions.upload_id` 컬럼이 없으면 추가한다. 추가하면 True."""
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_columns)
        if columns is None:
            logger.warning(
                "chat_sessions 테이블이 없어 upload_id 패치를 건너뜀"
            )
            return False
        added = False
        if "upload_id" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE chat_sessions ADD COLUMN upload_id INTEGER "
                    "NULL REFERENCES lessonplan_uploads(id) ON DELETE SET NULL"
                )
            )
            logger.info("chat_sessions.upload_id 컬럼을 추가함")
            added = True
        # SQLAlchemy index=True 기본 이름과 맞춰 새 DB와 같은 인덱스를 갖게 한다
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_sessions_upload_id "
                "ON chat_sessions(upload_id)"
            )
        )
        return added
