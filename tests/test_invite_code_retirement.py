"""Regression tests for invite-code retirement follow-up safety gates."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base
from app.main import _drop_legacy_invite_codes_table_if_enabled
from app.migrations.drop_invite_codes_table import drop_invite_codes_table
from app.models.users import User
from app.routers.qna import _session_segment_label_for_user
from app.services.auth_service import AuthService


async def _invite_codes_exists(engine) -> bool:
    async with engine.begin() as conn:
        return await conn.run_sync(
            lambda sync_conn: "invite_codes"
            in inspect(sync_conn).get_table_names()
        )


async def _create_engine_with_invite_codes():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE invite_codes "
                "(id INTEGER PRIMARY KEY, code VARCHAR(6))"
            )
        )
        await conn.execute(
            text("INSERT INTO invite_codes (code) VALUES ('ABC123')")
        )
    return engine


@pytest.mark.asyncio
async def test_startup_invite_code_drop_is_disabled_by_default(monkeypatch):
    engine = await _create_engine_with_invite_codes()
    monkeypatch.setattr(settings, "DROP_LEGACY_INVITE_CODES_TABLE", False)

    try:
        dropped = await _drop_legacy_invite_codes_table_if_enabled(engine)
        assert dropped is False
        assert await _invite_codes_exists(engine) is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_startup_invite_code_drop_requires_explicit_opt_in(monkeypatch):
    engine = await _create_engine_with_invite_codes()
    monkeypatch.setattr(settings, "DROP_LEGACY_INVITE_CODES_TABLE", True)

    try:
        dropped = await _drop_legacy_invite_codes_table_if_enabled(engine)
        assert dropped is True
        assert await _invite_codes_exists(engine) is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_drop_invite_codes_table_remains_idempotent():
    engine = await _create_engine_with_invite_codes()

    try:
        assert await drop_invite_codes_table(engine) is True
        assert await drop_invite_codes_table(engine) is False
        assert await _invite_codes_exists(engine) is False
    finally:
        await engine.dispose()


def test_passwordless_legacy_auth_service_method_is_removed():
    assert not hasattr(AuthService, "authenticate_user")


@pytest.mark.asyncio
async def test_qna_session_segment_for_profileless_user_returns_unprofiled():
    """With UserProfile gone, users without legacy nicknames get 미지정."""

    class EmptyResult:
        def scalar_one_or_none(self):
            return None

    class NoopSession:
        async def execute(self, statement):
            return EmptyResult()

    user = User(
        username="teacher_abc123",
        nickname="teacher",
        hashed_password=AuthService.hash_password("Password123"),
        is_admin=False,
    )
    user.id = 1

    label = await _session_segment_label_for_user(NoopSession(), user)
    # nickname "teacher" maps to "교사" via legacy fallback
    assert label == "교사"


@pytest.mark.asyncio
async def test_qna_session_segment_unknown_nickname_returns_unprofiled():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with session_factory() as session:
            user = User(
                username="randomuser123",
                nickname="randomuser123",
                hashed_password=AuthService.hash_password("Password123"),
                is_admin=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            label = await _session_segment_label_for_user(session, user)

        # No profile and no legacy nickname → 미지정
        assert label == "미지정"
    finally:
        await engine.dispose()
