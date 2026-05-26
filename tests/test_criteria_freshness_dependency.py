"""Tests for Issue #80 — list-call triggered freshness dependency."""
from unittest.mock import AsyncMock, patch

import pytest


def test_settings_has_list_reconcile_ttl():
    from app.config import settings
    assert isinstance(settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS, int)
    assert settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS >= 0


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
