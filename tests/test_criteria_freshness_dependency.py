"""Tests for Issue #80 — list-call triggered freshness dependency."""
import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def test_settings_has_list_reconcile_ttl():
    from app.config import settings
    assert isinstance(settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS, int)
    assert settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS >= 0


async def _keep_loop_awake():
    while True:
        await asyncio.sleep(0.01)


def _make_alias_fetch_failure_services():
    fake_client = MagicMock()
    fake_client.file_search_stores.list.return_value = []

    fake_vec = MagicMock()
    fake_vec.file_search_service.client = fake_client
    fake_vec.list_criteria_documents = AsyncMock(return_value=[])

    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(side_effect=RuntimeError("cloud 503"))
    return fake_vec, fake_alias


@pytest.mark.asyncio
async def test_freshness_dependency_calls_reconcile_when_ttl_expired(monkeypatch):
    from app.services import criteria_freshness as cf

    cf._reset_throttle_for_test()
    monkeypatch.setattr(
        cf.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True
    )
    monkeypatch.setattr(
        cf.settings, "CRITERIA_LIST_RECONCILE_TTL_SECONDS", 0
    )

    with patch.object(
        cf, "_run_reconcile_once", new=AsyncMock()
    ) as run:
        await cf.ensure_criteria_cache_fresh()
        await cf.ensure_criteria_cache_fresh()
    assert run.await_count == 2


@pytest.mark.asyncio
async def test_freshness_dependency_throttles_within_ttl(monkeypatch):
    from app.services import criteria_freshness as cf

    cf._reset_throttle_for_test()
    monkeypatch.setattr(
        cf.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True
    )
    monkeypatch.setattr(
        cf.settings, "CRITERIA_LIST_RECONCILE_TTL_SECONDS", 60
    )

    with patch.object(
        cf, "_run_reconcile_once", new=AsyncMock()
    ) as run:
        await cf.ensure_criteria_cache_fresh()
        await cf.ensure_criteria_cache_fresh()
        await cf.ensure_criteria_cache_fresh()
    assert run.await_count == 1


@pytest.mark.asyncio
async def test_freshness_dependency_noop_when_reconcile_disabled(monkeypatch):
    from app.services import criteria_freshness as cf

    cf._reset_throttle_for_test()
    monkeypatch.setattr(
        cf.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", False
    )
    monkeypatch.setattr(
        cf.settings, "CRITERIA_LIST_RECONCILE_TTL_SECONDS", 0
    )

    with patch.object(
        cf, "_run_reconcile_once", new=AsyncMock()
    ) as run:
        await cf.ensure_criteria_cache_fresh()
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_freshness_dependency_swallows_exceptions(monkeypatch):
    from app.services import criteria_freshness as cf

    cf._reset_throttle_for_test()
    monkeypatch.setattr(
        cf.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True
    )
    monkeypatch.setattr(
        cf.settings, "CRITERIA_LIST_RECONCILE_TTL_SECONDS", 0
    )

    async def boom():
        raise RuntimeError("cloud 503")

    with patch.object(cf, "_run_reconcile_once", new=boom):
        await cf.ensure_criteria_cache_fresh()  # raises 안 되어야 함


@pytest.mark.asyncio
async def test_ensure_cache_fresh_with_alias_fetch_failure_preserves_sync_state(
    monkeypatch,
):
    from app.db import Base
    from app.models import app_state as _app_state_model  # noqa: F401
    from app.repositories.app_state_repository import (
        AppStateRepository,
        KEY_API_KEY_HASH,
        KEY_SYNC_ERROR,
        KEY_SYNC_STATE,
    )
    from app.services import criteria_freshness as cf

    cf._reset_throttle_for_test()
    monkeypatch.setattr(cf.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True)
    monkeypatch.setattr(cf.settings, "CRITERIA_LIST_RECONCILE_TTL_SECONDS", 0)

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ticker = asyncio.create_task(_keep_loop_awake())

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            state = AppStateRepository(db)
            await state.set(KEY_API_KEY_HASH, "samehash")
            await state.set(KEY_SYNC_STATE, "ok")
            await state.set(KEY_SYNC_ERROR, "previous-error")
            await state.set("criteria_migration_v2_done", "true")
            await db.commit()

        fake_vec, fake_alias = _make_alias_fetch_failure_services()

        monkeypatch.setattr("app.db.async_session_maker", session_factory)
        with (
            patch(
                "app.services.criteria_vector_service.CriteriaVectorService",
                return_value=fake_vec,
            ),
            patch(
                "app.services.criteria_alias_map_service.CriteriaAliasMapService",
                return_value=fake_alias,
            ),
            patch(
                "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
                return_value="samehash",
            ),
        ):
            await cf.ensure_criteria_cache_fresh()

        async with session_factory() as db:
            state = AppStateRepository(db)
            assert await state.get(KEY_SYNC_STATE) == "ok"
            assert await state.get(KEY_SYNC_ERROR) == "previous-error"
    finally:
        await engine.dispose()
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker


@pytest.mark.asyncio
async def test_explicit_reconcile_marks_needs_resync_on_alias_fetch_failure():
    from app.db import Base
    from app.models import app_state as _app_state_model  # noqa: F401
    from app.repositories.app_state_repository import (
        AppStateRepository,
        KEY_API_KEY_HASH,
        KEY_SYNC_ERROR,
        KEY_SYNC_STATE,
    )
    from app.repositories.criteria_repository import CriteriaRepository
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ticker = asyncio.create_task(_keep_loop_awake())

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            state = AppStateRepository(db)
            await state.set(KEY_API_KEY_HASH, "samehash")
            await state.set(KEY_SYNC_STATE, "ok")
            await state.set(KEY_SYNC_ERROR, None)
            await state.set("criteria_migration_v2_done", "true")
            await db.commit()

        fake_vec, fake_alias = _make_alias_fetch_failure_services()

        async with session_factory() as db:
            state = AppStateRepository(db)
            svc = CriteriaReconciliationService(
                db=db,
                vector_service=fake_vec,
                alias_map_service=fake_alias,
                criteria_repo=CriteriaRepository(db=db),
                app_state_repo=state,
            )
            with patch(
                "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
                return_value="samehash",
            ):
                result = await svc.reconcile()

            assert result.ok is False
            assert result.error == "cloud 503"
            assert await state.get(KEY_SYNC_STATE) == "needs_resync"
            assert await state.get(KEY_SYNC_ERROR) == "cloud 503"
    finally:
        await engine.dispose()
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker
