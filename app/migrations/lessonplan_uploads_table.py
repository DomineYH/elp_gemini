"""
lessonplan_uploads 테이블 + analysis_reports.upload_id 컬럼 idempotent 적용.

SQLite은 ALTER TABLE ADD CONSTRAINT 를 지원하지 않으므로,
UNIQUE 제약 대신 UNIQUE INDEX 로 1:1 을 보장한다 (NULL 다중 허용은 동일).
"""
from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _collect_columns(sync_conn, table: str) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except NoSuchTableError:
        return None


def _collect_index_names(sync_conn, table: str) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except NoSuchTableError:
        return None


def _collect_table_names(sync_conn) -> Set[str]:
    return set(inspect(sync_conn).get_table_names())


async def ensure_lessonplan_uploads_table(engine: AsyncEngine) -> bool:
    """
    Idempotent 적용:
      1) lessonplan_uploads 테이블이 없으면 생성
      2) analysis_reports.upload_id 컬럼이 없으면 추가
      3) uq_analysis_reports_upload_id UNIQUE INDEX 가 없으면 생성

    Returns:
        하나라도 변경했으면 True, 모두 이미 있으면 False
    """
    async with engine.begin() as conn:
        tables = await conn.run_sync(_collect_table_names)
        changed = False

        if "lessonplan_uploads" not in tables:
            await conn.execute(text("""
                CREATE TABLE lessonplan_uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id)
                        ON DELETE CASCADE,
                    filename VARCHAR(500) NOT NULL,
                    original_filename VARCHAR(500),
                    file_hash VARCHAR(64),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text(
                "CREATE INDEX ix_lessonplan_uploads_user_id "
                "ON lessonplan_uploads(user_id)"
            ))
            await conn.execute(text(
                "CREATE INDEX ix_lessonplan_uploads_created_at "
                "ON lessonplan_uploads(created_at)"
            ))
            logger.info("lessonplan_uploads 테이블 생성")
            changed = True

        ar_columns = await conn.run_sync(
            lambda c: _collect_columns(c, "analysis_reports")
        )
        if ar_columns is not None and "upload_id" not in ar_columns:
            await conn.execute(text(
                "ALTER TABLE analysis_reports "
                "ADD COLUMN upload_id INTEGER REFERENCES "
                "lessonplan_uploads(id)"
            ))
            logger.info("analysis_reports.upload_id 컬럼 추가")
            changed = True

        ar_indexes = await conn.run_sync(
            lambda c: _collect_index_names(c, "analysis_reports")
        )
        if (
            ar_indexes is not None
            and "uq_analysis_reports_upload_id" not in ar_indexes
        ):
            await conn.execute(text(
                "CREATE UNIQUE INDEX uq_analysis_reports_upload_id "
                "ON analysis_reports(upload_id) "
                "WHERE upload_id IS NOT NULL"
            ))
            logger.info(
                "analysis_reports.upload_id UNIQUE INDEX 생성"
            )
            changed = True

        return changed
