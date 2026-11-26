"""#468: users.id를 AUTOINCREMENT로 바꾸는 재구성 마이그레이션."""

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.migrations import ensure_users_id_autoincrement
from app.migrations.users_id_autoincrement import _sequence_floor
from app.models.users import User

# 전환 전 운영·개발 DB의 users (2026-11-26 DB 사본의 sqlite_master 그대로)
OLD_USERS_SQL = [
    """
    CREATE TABLE users (
        id INTEGER NOT NULL,
        username VARCHAR(255) NOT NULL,
        nickname VARCHAR(255) NOT NULL,
        hashed_password VARCHAR(255),
        is_admin BOOLEAN NOT NULL,
        failed_login_count INTEGER DEFAULT '0' NOT NULL,
        locked_until DATETIME,
        last_failed_login_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        session_version INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (id)
    )
    """,
    "CREATE UNIQUE INDEX ix_users_username ON users (username)",
    "CREATE INDEX ix_users_id ON users (id)",
]
USER_IDS = (1, 2, 3, 4, 99)
# 재구성 뒤 열 순서는 모델 순서가 되므로 이름으로 비교한다
USER_COLUMNS = ", ".join(User.__table__.columns.keys())
CHILD_SQL = {
    "chat_sessions": (
        "INSERT INTO chat_sessions (user_id, user_type, title) "
        "VALUES (3, '교사', 't')"
    ),
    "analysis_reports": (
        "INSERT INTO analysis_reports (user_id, lessonplan_filename, "
        "report_filename, report_path, latency_ms) "
        "VALUES (3, 'p.pdf', 'r.md', 'r.md', 1)"
    ),
    "lessonplan_uploads": (
        "INSERT INTO lessonplan_uploads (id, user_id, filename) "
        "VALUES (1, 4, 'p.pdf')"
    ),
    "simulation_sessions": (
        "INSERT INTO simulation_sessions (user_id, upload_id, persona_count, "
        "model_name) VALUES (4, 1, 4, 'm')"
    ),
    "simulation_persona_library": (
        "INSERT INTO simulation_persona_library (user_id, raw_profile, "
        "adapted_profile, adapted_level) VALUES (4, '{}', '{}', '중')"
    ),
}
CASCADE_CHILDREN = (
    "lessonplan_uploads",
    "simulation_sessions",
    "simulation_persona_library",
)


@pytest_asyncio.fixture
async def old_db(tmp_path):
    """옛 DDL의 users 5행과 모델로 만든 나머지 표. 앱처럼 FK를 켠다."""
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'old.db'}", poolclass=StaticPool
    )

    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with eng.begin() as conn:
        for sql in OLD_USERS_SQL:
            await conn.execute(text(sql))
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c,
                tables=[
                    t for t in Base.metadata.sorted_tables if t.name != "users"
                ],
            )
        )
        for uid in USER_IDS:
            await conn.execute(
                text(
                    "INSERT INTO users (id, username, nickname, "
                    "hashed_password, is_admin, session_version) "
                    "VALUES (:id, :name, :name, 'h', :admin, :id)"
                ),
                {"id": uid, "name": f"u{uid}", "admin": uid == 1},
            )
    yield eng
    await eng.dispose()


async def _seed_children(eng, tables):
    async with eng.begin() as conn:
        for table in tables:
            await conn.execute(text(CHILD_SQL[table]))


async def _snapshot(eng):
    async with eng.connect() as conn:

        async def rows(sql):
            return [tuple(r) for r in await conn.execute(text(sql))]

        fks = []
        for (child,) in await rows(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            fks += [
                (child, r[3], r[6])
                for r in await rows(f"PRAGMA foreign_key_list({child})")
                if r[2] == "users"
            ]
        return {
            "users": await rows(
                f"SELECT {USER_COLUMNS} FROM users ORDER BY id"
            ),
            "children": {
                t: (await rows(f"SELECT count(*) FROM {t}"))[0][0]
                for t in CHILD_SQL
            },
            "indexes": await rows(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='index' AND tbl_name='users' ORDER BY name"
            ),
            "fks": sorted(fks),
        }


async def _scalar(eng, sql):
    async with eng.connect() as conn:
        return (await conn.execute(text(sql))).scalar_one_or_none()


USERS_DDL = "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
USERS_SEQ = "SELECT seq FROM sqlite_sequence WHERE name='users'"


@pytest.mark.parametrize(
    "max_id, floor",
    [(None, 1000), (99, 1000), (999, 1000), (1000, 2000), (2500, 3000)],
)
def test_sequence_floor(max_id, floor):
    assert _sequence_floor(max_id) == floor


@pytest.mark.asyncio
async def test_rebuild_keeps_rows_indexes_and_foreign_keys(old_db):
    await _seed_children(old_db, CHILD_SQL)
    before = await _snapshot(old_db)
    assert len(before["fks"]) == 6
    assert before["indexes"][1][1].startswith("CREATE UNIQUE INDEX")

    assert await ensure_users_id_autoincrement(old_db) is True

    assert await _snapshot(old_db) == before
    assert "AUTOINCREMENT" in await _scalar(old_db, USERS_DDL)
    assert await _scalar(old_db, USERS_SEQ) == 1000
    assert await _scalar(old_db, "PRAGMA foreign_keys") == 1
    async with old_db.connect() as conn:
        violations = await conn.execute(text("PRAGMA foreign_key_check"))
        assert violations.fetchall() == []

    # 전환 뒤에는 가장 최근 가입자를 지워도 id가 다시 나오지 않는다
    async with old_db.begin() as conn:
        insert = text(
            "INSERT INTO users (username, nickname, is_admin) "
            "VALUES (:n, :n, 0)"
        )
        first = (await conn.execute(insert, {"n": "v"})).lastrowid
        await conn.execute(
            text("DELETE FROM users WHERE id = :i"), {"i": first}
        )
        second = (await conn.execute(insert, {"n": "n"})).lastrowid
    assert (first, second) == (1001, 1002)


@pytest.mark.asyncio
async def test_rebuild_does_not_cascade_into_child_rows(old_db):
    """대화·보고서 행이 없으면 FK가 켜진 재구성은 CASCADE 자식을 지운다."""
    await _seed_children(old_db, CASCADE_CHILDREN)
    before = await _snapshot(old_db)

    assert await ensure_users_id_autoincrement(old_db) is True

    after = await _snapshot(old_db)
    assert after["children"] == before["children"]
    assert all(after["children"][t] == 1 for t in CASCADE_CHILDREN)


@pytest.mark.asyncio
async def test_second_run_changes_nothing(old_db):
    assert await ensure_users_id_autoincrement(old_db) is True
    dump = "SELECT group_concat(sql, ';') FROM sqlite_master"
    before = (await _snapshot(old_db), await _scalar(old_db, dump))
    async with old_db.begin() as conn:
        await conn.execute(text("UPDATE sqlite_sequence SET seq = 1234"))

    assert await ensure_users_id_autoincrement(old_db) is False

    assert (await _snapshot(old_db), await _scalar(old_db, dump)) == before
    assert await _scalar(old_db, USERS_SEQ) == 1234


@pytest.mark.asyncio
async def test_unknown_column_aborts_and_leaves_table(old_db):
    await _seed_children(old_db, CASCADE_CHILDREN)
    async with old_db.begin() as conn:
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN legacy_note TEXT")
        )
    before = (await _snapshot(old_db), await _scalar(old_db, USERS_DDL))

    with pytest.raises(RuntimeError, match="legacy_note"):
        await ensure_users_id_autoincrement(old_db)

    assert (await _snapshot(old_db), await _scalar(old_db, USERS_DDL)) == before
    assert await _scalar(old_db, "PRAGMA foreign_keys") == 1
    assert (
        await _scalar(
            old_db, "SELECT count(*) FROM sqlite_master WHERE name='users_new'"
        )
        == 0
    )


@pytest.mark.asyncio
async def test_empty_users_table_still_gets_floor(old_db):
    async with old_db.begin() as conn:
        await conn.execute(text("DELETE FROM users"))

    assert await ensure_users_id_autoincrement(old_db) is True

    assert await _scalar(old_db, USERS_SEQ) == 1000


@pytest.mark.asyncio
async def test_create_all_makes_users_autoincrement(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'new.db'}")
    try:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        assert "AUTOINCREMENT" in await _scalar(eng, USERS_DDL)
        assert await ensure_users_id_autoincrement(eng) is False
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_startup_converts_after_users_column_migrations(
    tmp_path, monkeypatch
):
    """startup은 email 제거·session_version 보정 뒤에 전환한다."""
    import app.main as main_mod

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(main_mod, "engine", eng)
    monkeypatch.setattr(main_mod.settings, "DEBUG", False)
    monkeypatch.setattr(main_mod.settings, "ADMIN_INITIAL_PASSWORD", None)
    try:
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE users (id INTEGER NOT NULL, "
                    "username VARCHAR(255) NOT NULL, "
                    "nickname VARCHAR(255) NOT NULL, email VARCHAR(255), "
                    "hashed_password VARCHAR(255), is_admin BOOLEAN NOT NULL, "
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                    "PRIMARY KEY (id))"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO users (id, username, nickname, email, "
                    "is_admin) VALUES (7, 'old', 'Old', 'o@example.com', 0)"
                )
            )

        for _ in range(2):  # 재실행 멱등
            await main_mod.startup_event()
            assert "AUTOINCREMENT" in await _scalar(eng, USERS_DDL)
            assert await _scalar(eng, USERS_SEQ) == 1000
            async with eng.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT id, username, session_version FROM users")
                    )
                ).one()
            assert tuple(row) == (7, "old", 0)
    finally:
        await eng.dispose()
