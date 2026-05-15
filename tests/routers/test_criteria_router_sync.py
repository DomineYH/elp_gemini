# tests/routers/test_criteria_router_sync.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.routers.admin.criteria import upload_criteria


@pytest.fixture
def admin_client():
    from app.db import get_db
    from app.dependencies import get_current_admin

    app.dependency_overrides[get_current_admin] = lambda: object()

    async def _fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _fake_db
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
    ) as repo_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as crit_cls:
        mock_state = AsyncMock()
        mock_state.get = AsyncMock(
            side_effect=lambda k: {
                "criteria_sync_state": "ok",
                "criteria_last_synced_at": "2026-05-15T00:00Z",
                "criteria_sync_error": None,
            }.get(k)
        )
        repo_cls.return_value = mock_state
        crit_instance = crit_cls.return_value
        crit_instance.get_all_criteria = AsyncMock(return_value=[])

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


@pytest.mark.asyncio
async def test_upload_does_not_publish_manifest_before_cloud_document_exists():
    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db = AsyncMock()
    current_admin = SimpleNamespace(username="admin")
    criteria = SimpleNamespace(id=123, file_path="temp")

    with patch(
        "app.routers.admin.criteria.FileValidator"
    ) as validator_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.services.file_storage_service.FileStorageService"
    ) as storage_cls, patch(
        "app.routers.admin.criteria._publish_or_mark_resync",
        new_callable=AsyncMock,
    ) as publish:
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        repo_cls.return_value.save_criteria = AsyncMock(return_value=criteria)
        storage_cls.return_value.save_file = MagicMock(
            return_value="/criteria/123_rubric.pdf"
        )

        response = await upload_criteria(
            file=file,
            current_admin=current_admin,
            db=db,
            _sync_ready=None,
        )

    assert response.file_id == "123"
    publish.assert_not_awaited()
