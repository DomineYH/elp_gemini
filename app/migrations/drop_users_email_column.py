"""
users.email 컬럼 제거 마이그레이션 도우미

SQLite < 3.35 cannot DROP UNIQUE columns; this migration falls back to
a table rebuild (create new → copy data → drop old → rename) when the
simple ALTER TABLE fails.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Columns to preserve (in order) when rebuilding the users table.
_USERS_COLUMNS_NO_EMAIL = (
    "id, username, nickname, hashed_password, is_admin, "
    "failed_login_count, locked_until, last_failed_login_at, "
    "created_at, updated_at"
)

# Inbound FK indexes that reference users.id.
# Only created if the child table exists.
_FK_INDEX_DEFS = [
    (
        "chat_sessions",
        "CREATE INDEX IF NOT EXISTS "
        "ix_chat_sessions_user_id ON chat_sessions (user_id)",
    ),
    (
        "analysis_reports",
        "CREATE INDEX IF NOT EXISTS "
        "ix_analysis_reports_user_id ON analysis_reports (user_id)",
    ),
    (
        "lessonplan_uploads",
        "CREATE INDEX IF NOT EXISTS "
        "ix_lessonplan_uploads_user_id ON lessonplan_uploads (user_id)",
    ),
]


async def _rebuild_users_without_email(engine: AsyncEngine) -> None:
    """
    Rebuild the users table without the email column.

    Order matters: the old ``users`` table (and its global index names
    ``ix_users_id``, ``ix_users_username``) must be **dropped before** the
    new indexes are created, otherwise SQLite raises
    ``OperationalError: index … already exists``.

    ``PRAGMA foreign_keys`` is toggled outside the transaction (SQLite
    requirement) so the intermediate parent-less state does not trip FK
    enforcement.
    """
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")

        table_exists = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("users")
        )
        if not table_exists:
            return

        has_email = await conn.run_sync(
            lambda sync_conn: "email"
            in {c["name"] for c in inspect(sync_conn).get_columns("users")}
        )
        await conn.commit()
        if not has_email:
            return

        # Temporarily disable FK enforcement before opening the explicit
        # rebuild transaction. SQLite ignores this PRAGMA inside a txn.
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.commit()

        transaction_open = False
        try:
            await conn.execute(text("BEGIN"))
            transaction_open = True
            await conn.execute(text("DROP TABLE IF EXISTS users_new"))

            # 1. Create bare table (no secondary indexes yet)
            await conn.execute(text("""
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    nickname VARCHAR(255) NOT NULL,
                    hashed_password VARCHAR(255),
                    is_admin BOOLEAN NOT NULL DEFAULT 0,
                    failed_login_count INTEGER NOT NULL DEFAULT 0,
                    locked_until DATETIME,
                    last_failed_login_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # 2. Copy data
            await conn.execute(text(
                "INSERT INTO users_new ({cols}) SELECT {cols} FROM users"
                .format(cols=_USERS_COLUMNS_NO_EMAIL)
            ))

            # 3. Drop old table — frees global index names
            await conn.execute(text("DROP TABLE users"))

            # 4. Rename new → users
            await conn.execute(text("ALTER TABLE users_new RENAME TO users"))

            # 5. NOW create secondary indexes on the renamed table
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_users_id ON users (id)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_users_username ON users (username)"
            ))

            # 6. Restore inbound FK indexes (only for tables that exist)
            existing_tables = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )
            for child_table, create_sql in _FK_INDEX_DEFS:
                if child_table in existing_tables:
                    await conn.execute(text(create_sql))

            await conn.execute(text("COMMIT"))
            transaction_open = False
            await conn.commit()
        except Exception:
            if transaction_open:
                await conn.execute(text("ROLLBACK"))
            await conn.commit()
            raise
        finally:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            await conn.commit()


async def drop_users_email_column(engine: AsyncEngine) -> bool:
    """
    users 테이블에서 email 컬럼과 관련 인덱스를 제거한다.

    Returns:
        컬럼이 존재해 제거했으면 True, 이미 없으면 False
    """
    async with engine.begin() as conn:
        table_exists = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("users")
        )

        if not table_exists:
            logger.debug(
                "users 테이블이 없어 email 컬럼 제거 마이그레이션을 건너뜀"
            )
            return False

        has_email = await conn.run_sync(
            lambda sync_conn: "email"
            in {c["name"] for c in inspect(sync_conn).get_columns("users")}
        )

        if not has_email:
            logger.debug(
                "users.email 컬럼이 없어 제거 마이그레이션을 건너뜀"
            )
            return False

        logger.info("users.email 컬럼 제거 진행")

        # Try simple DROP COLUMN first (works on SQLite >= 3.35.0
        # for non-UNIQUE columns)
        try:
            await conn.execute(
                text("DROP INDEX IF EXISTS ix_users_email")
            )
            await conn.execute(
                text("ALTER TABLE users DROP COLUMN email")
            )
            logger.info("users.email 컬럼 제거 완료 (ALTER TABLE)")
            return True
        except Exception:
            # UNIQUE constraint prevents simple DROP; rebuild table instead
            logger.info(
                "ALTER TABLE DROP COLUMN 실패 → 테이블 재구성으로 전환"
            )

    # Rebuild uses its own transaction
    await _rebuild_users_without_email(engine)
    logger.info("users.email 컬럼 제거 완료 (테이블 재구성)")
    return True
