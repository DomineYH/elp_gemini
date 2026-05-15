# tests/test_startup_reconcile.py
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_startup_schedules_reconcile_when_enabled(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(
        main_module.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True
    )
    with patch(
        "app.main._run_criteria_reconcile_in_background"
    ) as run:
        await main_module.startup_event()
    run.assert_called_once()


@pytest.mark.asyncio
async def test_startup_skips_reconcile_when_disabled(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(
        main_module.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", False
    )
    with patch(
        "app.main._run_criteria_reconcile_in_background"
    ) as run:
        await main_module.startup_event()
    run.assert_not_called()
