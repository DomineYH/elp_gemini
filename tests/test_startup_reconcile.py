# tests/test_startup_reconcile.py
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_startup_schedules_reconcile_when_enabled(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(
        main_module.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True
    )
    with patch("app.main._run_criteria_reconcile_in_background") as run:
        await main_module.startup_event()
    run.assert_called_once()


@pytest.mark.asyncio
async def test_startup_skips_reconcile_when_disabled(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(
        main_module.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", False
    )
    with patch("app.main._run_criteria_reconcile_in_background") as run:
        await main_module.startup_event()
    run.assert_not_called()


@pytest.mark.asyncio
async def test_startup_reconcile_db_failure_hides_sql_params(caplog):
    """#485: 시작 재동기화의 상태 조회가 DB 오류로 실패해도 SQL 바인딩 값이 로그에 없다."""
    from unittest.mock import AsyncMock

    from sqlalchemy.exc import IntegrityError

    from app import main as main_module

    failure = IntegrityError(
        "SELECT value FROM app_state WHERE key = ?",
        ("sensitive-marker",),
        Exception("locked"),
    )
    with (
        patch(
            "app.repositories.app_state_repository.AppStateRepository.get",
            AsyncMock(side_effect=failure),
        ),
        patch("app.services.criteria_vector_service.CriteriaVectorService"),
        patch(
            "app.services.criteria_alias_map_service.CriteriaAliasMapService"
        ),
    ):
        await main_module._run_criteria_reconcile_in_background()
        for task in list(main_module._background_tasks):
            await task

    assert "startup reconcile 실패: IntegrityError" in caplog.text
    assert "sensitive-marker" not in caplog.text
