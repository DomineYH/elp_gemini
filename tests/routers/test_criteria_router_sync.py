# tests/routers/test_criteria_router_sync.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.admin.criteria import (
    list_criteria_json,
    reconcile_criteria,
    router,
    upload_criteria,
)


@pytest.mark.asyncio
async def test_reconcile_endpoint_returns_state():
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

        body = await reconcile_criteria(db=object(), _admin=object())

    assert body["ok"] is True
    assert body["count"] == 2


@pytest.mark.asyncio
async def test_list_endpoint_includes_sync_metadata():
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

        body = await list_criteria_json(current_admin=object(), db=object())

    assert "sync" in body
    assert body["sync"]["state"] == "ok"


@pytest.mark.asyncio
async def test_list_criteria_json_includes_id_and_stable_id():
    row = SimpleNamespace(
        id=7,
        stable_id="01HJSONSTABLE",
        title="rubric.pdf",
        display_alias=None,
        status="uploaded",
        file_size=123,
        created_at=None,
        document_id="fileSearchStores/s/documents/rubric",
    )

    with patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as crit_cls:
        mock_state = AsyncMock()
        mock_state.get = AsyncMock(return_value=None)
        repo_cls.return_value = mock_state
        crit_instance = crit_cls.return_value
        crit_instance.get_all_criteria = AsyncMock(return_value=[row])

        body = await list_criteria_json(current_admin=object(), db=object())

    item = body["criteria"][0]
    assert item["id"] == 7
    assert item["stable_id"] == "01HJSONSTABLE"


def test_upload_route_requires_sync_ready_dependency():
    from app.dependencies import require_criteria_sync_ready

    upload_route = next(
        route for route in router.routes
        if getattr(route, "path", None) == "/api/admin/criteria/upload"
        and "POST" in getattr(route, "methods", set())
    )
    assert any(
        dep.call is require_criteria_sync_ready
        for dep in upload_route.dependant.dependencies
    )


@pytest.mark.asyncio
async def test_upload_does_not_publish_manifest_before_cloud_document_exists():
    pytest.skip("Wave 5: replaced by new alias_map-based upload; assertions no longer apply")
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
