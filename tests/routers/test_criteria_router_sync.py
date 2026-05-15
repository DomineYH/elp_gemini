# tests/routers/test_criteria_router_sync.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def admin_client():
    from app.dependencies import get_current_admin

    app.dependency_overrides[get_current_admin] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_reconcile_endpoint_returns_state(admin_client):
    mock_result = type(
        "R", (), {"ok": True, "skipped": False, "count": 2, "error": None}
    )()

    with patch(
        "app.routers.admin.criteria.CriteriaReconciliationService"
    ) as svc_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as repo_cls:
        instance = svc_cls.return_value
        instance.reconcile = AsyncMock(return_value=mock_result)
        mock_state = AsyncMock()
        mock_state.get = AsyncMock(return_value="ok")
        repo_cls.return_value = mock_state

        resp = admin_client.post("/api/admin/criteria/reconcile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["count"] == 2


def test_list_endpoint_includes_sync_metadata(admin_client):
    with patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as repo_cls:
        mock_state = AsyncMock()
        mock_state.get = AsyncMock(
            side_effect=lambda k: {
                "criteria_sync_state": "ok",
                "criteria_last_synced_at": "2026-05-15T00:00Z",
                "criteria_sync_error": None,
            }.get(k)
        )
        repo_cls.return_value = mock_state

        resp = admin_client.get("/api/admin/criteria")

    assert resp.status_code == 200
    body = resp.json()
    assert "sync" in body
    assert body["sync"]["state"] == "ok"


def test_mutation_blocked_when_sync_state_not_ok(admin_client):
    from app.dependencies import require_criteria_sync_ready

    async def blocked():
        raise HTTPException(
            status_code=503, detail="blocked"
        )

    app.dependency_overrides[require_criteria_sync_ready] = blocked
    resp = admin_client.post(
        "/api/admin/criteria/upload",
        files={"file": ("r.pdf", b"data", "application/pdf")},
    )
    assert resp.status_code == 503
    app.dependency_overrides.pop(require_criteria_sync_ready, None)
