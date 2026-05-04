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
from app.models.user_profiles import UserProfile
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
async def test_qna_session_segment_propagates_profile_query_errors():
    class BrokenSession:
        async def execute(self, statement):
            raise RuntimeError("profile query failed")

    user = User(
        username="teacher_abc123",
        nickname="teacher",
        email="teacher-segment@example.com",
        hashed_password=AuthService.hash_password("Password123"),
        is_admin=False,
    )
    user.id = 1

    with pytest.raises(RuntimeError, match="profile query failed"):
        await _session_segment_label_for_user(BrokenSession(), user)


@pytest.mark.asyncio
async def test_qna_session_segment_uses_profile_not_generated_username():
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
                username="preservice_teacher_abc123",
                nickname="preservice_teacher",
                email="preservice-segment@example.com",
                hashed_password=AuthService.hash_password("Password123"),
                is_admin=False,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserProfile(
                    user_id=user.id,
                    role="preservice_teacher",
                    preservice_university_region="서울",
                    preservice_grade=3,
                )
            )
            await session.commit()
            await session.refresh(user)

            label = await _session_segment_label_for_user(session, user)

        assert label == "3학년"
    finally:
        await engine.dispose()
