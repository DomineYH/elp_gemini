"""
lessonplan_uploads.fs_document_id / fs_store_id 컬럼 추가 (#173)

GET /dashboard가 최근 업로드의 QnA 진입점(File Search 문서 ID)을 복원할 수
있도록 업로드 시 문서·스토어 이름을 저장한다. 과거 행은 NULL로 남아 지금처럼
업로드 안내를 보인다.
"""

from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_COLUMNS = ("fs_document_id", "fs_store_id")


def _collect_columns(sync_conn) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        columns = inspector.get_columns("lessonplan_uploads")
    except NoSuchTableError:
        return None
    return {col["name"] for col in columns}


async def ensure_lessonplan_uploads_fs_id_columns(engine: AsyncEngine) -> bool:
    """없는 컬럼을 추가한다. 하나라도 추가하면 True."""
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_columns)
        if columns is None:
            logger.warning(
                "lessonplan_uploads 테이블이 없어 fs id 패치를 건너뜀"
            )
            return False
        added = False
        for name in _COLUMNS:
            if name in columns:
                continue
            await conn.execute(
                text(
                    f"ALTER TABLE lessonplan_uploads "
                    f"ADD COLUMN {name} VARCHAR(512) NULL"
                )
            )
            logger.info("lessonplan_uploads.%s 컬럼 추가", name)
            added = True
        return added
