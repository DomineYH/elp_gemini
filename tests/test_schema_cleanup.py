"""Issue #91 §3+§5: UserProfile table & User.email column removal tests."""

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def test_user_model_has_no_email():
    from app.models.users import User

    assert "email" not in User.__table__.columns


def test_userprofile_module_gone():
    with pytest.raises(ModuleNotFoundError):
        __import__("app.models.user_profiles")


def test_user_model_has_no_profile_relationship():
    """The 'profile' relationship must have been removed from User."""
    from app.models.users import User

    rel_names = {rel.key for rel in User.__mapper__.relationships}
    assert "profile" not in rel_names


def test_user_has_no_userprofile_import():
    """app.models.users must not import UserProfile."""
    import app.models.users as users_mod

    source = open(users_mod.__file__, encoding="utf-8").read()
    assert "UserProfile" not in source


@pytest.mark.asyncio
async def test_drop_user_profiles_migration():
    """Fresh DB → run drop_user_profiles → table absent."""
    from app.migrations.drop_user_profiles import drop_user_profiles

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
    )
    try:
        # Create the table first so we can verify it gets dropped
        async with eng.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE user_profiles (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    role VARCHAR(50) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

        dropped = await drop_user_profiles(eng)
        assert dropped is True

        async with eng.begin() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
        assert "user_profiles" not in tables

        # Idempotent: run again → False
        assert await drop_user_profiles(eng) is False
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_drop_users_email_column_migration():
    """Fresh DB with users.email → run migration → column absent."""
    from app.migrations.drop_users_email_column import (
        drop_users_email_column,
    )

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
    )
    try:
        # Create a users table WITH an email column + index
        async with eng.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    nickname VARCHAR(255) NOT NULL,
                    email VARCHAR(255) UNIQUE,
                    hashed_password VARCHAR(255),
                    is_admin BOOLEAN NOT NULL DEFAULT 0,
                    failed_login_count INTEGER NOT NULL DEFAULT 0,
                    locked_until DATETIME,
                    last_failed_login_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text(
                "CREATE INDEX ix_users_email ON users (email)"
            ))

        dropped = await drop_users_email_column(eng)
        assert dropped is True

        async with eng.begin() as conn:
            cols = await conn.run_sync(
                lambda sync_conn: [
                    c["name"] for c in inspect(sync_conn).get_columns("users")
                ]
            )
        assert "email" not in cols

        # Idempotent: run again → False
        assert await drop_users_email_column(eng) is False
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_both_migrations_on_fresh_empty_db():
    """On a DB with no users/user_profiles tables, migrations are no-ops."""
    from app.migrations.drop_user_profiles import drop_user_profiles
    from app.migrations.drop_users_email_column import (
        drop_users_email_column,
    )

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        assert await drop_user_profiles(eng) is False
        assert await drop_users_email_column(eng) is False
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_rebuild_path_preserves_data_and_child_fks():
    """
    Exercise the table-rebuild path directly.

    Builds a production-like schema with ix_users_id, ix_users_username,
    ix_users_email indexes + a chat_sessions child FK row, forces the
    rebuild helper, then asserts:
      - email column gone
      - user row preserved
      - child FK row preserved
      - PRAGMA foreign_key_check clean
      - idempotent (second run returns False)
    """
    from app.migrations.drop_users_email_column import (
        _rebuild_users_without_email,
    )

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(eng.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        # --- Set up production-like schema with indexes & data ---
        async with eng.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    nickname VARCHAR(255) NOT NULL,
                    email VARCHAR(255) UNIQUE,
                    hashed_password VARCHAR(255),
                    is_admin BOOLEAN NOT NULL DEFAULT 0,
                    failed_login_count INTEGER NOT NULL DEFAULT 0,
                    locked_until DATETIME,
                    last_failed_login_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            # Production indexes (the names that would collide if created
            # before DROP TABLE in the rebuild).
            await conn.execute(text(
                "CREATE INDEX ix_users_id ON users (id)"
            ))
            await conn.execute(text(
                "CREATE INDEX ix_users_username ON users (username)"
            ))
            await conn.execute(text(
                "CREATE INDEX ix_users_email ON users (email)"
            ))
            # Seed a user row
            await conn.execute(text("""
                INSERT INTO users (username, nickname, email, hashed_password,
                                   is_admin, failed_login_count)
                VALUES ('testuser', 'Test', 'test@example.com', 'hash', 0, 0)
            """))
            # Child table with FK → users.id
            await conn.execute(text("""
                CREATE TABLE chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title VARCHAR(255),
                    user_type VARCHAR(50),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                        ON DELETE CASCADE
                )
            """))
            await conn.execute(text(
                "CREATE INDEX ix_chat_sessions_user_id "
                "ON chat_sessions (user_id)"
            ))
            # Seed a child row referencing the user
            await conn.execute(text("""
                INSERT INTO chat_sessions (user_id, title, user_type)
                VALUES (1, 'test session', '미지정')
            """))

        # --- Run the rebuild directly ---
        await _rebuild_users_without_email(eng)

        # --- Verify ---
        async with eng.begin() as conn:
            fk_enabled = await conn.execute(text("PRAGMA foreign_keys"))
            assert fk_enabled.scalar_one() == 1

            cols = await conn.run_sync(
                lambda c: [
                    col["name"] for col in inspect(c).get_columns("users")
                ]
            )
            assert "email" not in cols, (
                f"email column still present: {cols}"
            )

            # User row preserved
            row = await conn.execute(
                text("SELECT username, nickname FROM users WHERE id = 1")
            )
            user = row.fetchone()
            assert user is not None
            assert user[0] == "testuser"
            assert user[1] == "Test"

            # Child FK row preserved
            child = await conn.execute(
                text(
                    "SELECT title, user_id FROM chat_sessions "
                    "WHERE user_id = 1"
                )
            )
            sess = child.fetchone()
            assert sess is not None
            assert sess[0] == "test session"
            assert sess[1] == 1

            # FK integrity
            fk_violations = await conn.execute(
                text("PRAGMA foreign_key_check")
            )
            assert fk_violations.fetchall() == [], "FK violations found"

        # Idempotent: running the rebuild helper again on an email-less table
        # should be a no-op and should preserve existing rows.
        await _rebuild_users_without_email(eng)
        async with eng.begin() as conn:
            users_count = await conn.execute(text("SELECT count(1) FROM users"))
            assert users_count.scalar_one() == 1
            sessions_count = await conn.execute(
                text("SELECT count(1) FROM chat_sessions")
            )
            assert sessions_count.scalar_one() == 1

        # The top-level function should also remain idempotent.
        from app.migrations.drop_users_email_column import (
            drop_users_email_column,
        )
        assert await drop_users_email_column(eng) is False
    finally:
        await eng.dispose()
