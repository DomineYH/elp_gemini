"""
users.id AUTOINCREMENT 전환 (#468)

AUTOINCREMENT가 없으면 가장 최근 가입자를 지운 뒤 다음 가입자가 같은 id를
받고, id에 묶인 로그인 쿠키·스토어·폴더가 새 가입자에게 넘어간다.
SQLite는 ALTER로 바꿀 수 없어 표를 재구성한다.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models.users import User

logger = logging.getLogger(__name__)


def _sequence_floor(max_id: Optional[int]) -> int:
    """다음 id의 바닥값: 1000, 최대 id가 그 이상이면 다음 천 단위."""
    return ((max_id or 0) // 1000 + 1) * 1000


async def _needs_rebuild(conn: AsyncConnection) -> bool:
    ddl = (
        await conn.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='users'"
            )
        )
    ).scalar_one_or_none()
    return ddl is not None and "AUTOINCREMENT" not in ddl.upper()


async def _fk_violations(conn: AsyncConnection) -> list:
    rows = (await conn.execute(text("PRAGMA foreign_key_check"))).fetchall()
    return sorted(tuple(map(str, row)) for row in rows)


async def ensure_users_id_autoincrement(engine: AsyncEngine) -> bool:
    """`users.id`가 AUTOINCREMENT가 아니면 표를 재구성한다.

    Returns:
        재구성했으면 True, 이미 AUTOINCREMENT이거나 표가 없으면 False
    """
    table = User.__table__
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        if not await _needs_rebuild(conn):
            return False

        # FK가 켜진 채 DROP TABLE users를 하면 ON DELETE CASCADE 자식 행이
        # 지워진다. 이 PRAGMA는 트랜잭션 안에서는 무시되므로 BEGIN 전에 끈다.
        fk_before = (
            await conn.execute(text("PRAGMA foreign_keys"))
        ).scalar_one()
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            fk_now = (
                await conn.execute(text("PRAGMA foreign_keys"))
            ).scalar_one()
            if fk_now != 0:
                raise RuntimeError(
                    "PRAGMA foreign_keys를 끄지 못해 users 재구성을 중단"
                )
            await conn.execute(text("BEGIN IMMEDIATE"))
            try:
                # 잠금을 기다리는 사이 다른 프로세스가 끝냈을 수 있다
                if not await _needs_rebuild(conn):
                    await conn.execute(text("ROLLBACK"))
                    return False

                live = [
                    row[1]
                    for row in await conn.execute(
                        text("PRAGMA table_info(users)")
                    )
                ]
                unknown = sorted(set(live) - set(table.columns.keys()))
                if unknown:
                    raise RuntimeError(
                        "users에 모델에 없는 열이 있어 재구성을 중단: "
                        + ", ".join(unknown)
                    )
                cols = ", ".join(f'"{name}"' for name in live)
                violations_before = await _fk_violations(conn)
                max_id = (
                    await conn.execute(text("SELECT max(id) FROM users"))
                ).scalar_one()

                await conn.execute(text("DROP TABLE IF EXISTS users_new"))
                await conn.execute(
                    CreateTable(table.to_metadata(MetaData(), name="users_new"))
                )
                await conn.execute(
                    text(
                        f"INSERT INTO users_new ({cols}) "
                        f"SELECT {cols} FROM users"
                    )
                )
                # 옛 표를 먼저 지워야 색인 이름(ix_users_*)이 풀린다
                await conn.execute(text("DROP TABLE users"))
                await conn.execute(
                    text("ALTER TABLE users_new RENAME TO users")
                )
                for index in sorted(table.indexes, key=lambda ix: ix.name):
                    await conn.execute(CreateIndex(index))

                # 빈 표는 sqlite_sequence 행이 없으므로 UPDATE가 아니라 새로 쓴다
                await conn.execute(
                    text("DELETE FROM sqlite_sequence WHERE name='users'")
                )
                await conn.execute(
                    text(
                        "INSERT INTO sqlite_sequence (name, seq) "
                        "VALUES ('users', :seq)"
                    ),
                    {"seq": _sequence_floor(max_id)},
                )

                if await _fk_violations(conn) != violations_before:
                    raise RuntimeError(
                        "users 재구성 뒤 foreign_key_check 결과가 달라져 중단"
                    )
                await conn.execute(text("COMMIT"))
            except BaseException:
                await conn.execute(text("ROLLBACK"))
                raise
        finally:
            await conn.execute(
                text(f"PRAGMA foreign_keys={'ON' if fk_before else 'OFF'}")
            )
    logger.info(
        "users.id AUTOINCREMENT 전환 완료: 다음 id는 %d보다 크다",
        _sequence_floor(max_id),
    )
    return True
