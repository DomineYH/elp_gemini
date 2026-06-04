"""Issue #91 §3+§5: UserProfile table & User.email column removal tests."""

import pytest
from sqlalchemy import inspect, text
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
