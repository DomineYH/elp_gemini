# tests/services/test_criteria_reconciliation_service.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.app_state_repository import (
    KEY_API_KEY_HASH,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    SYNC_STATE_OK,
)
from app.services.criteria_manifest_service import CloudUnavailable
from app.services.criteria_reconciliation_service import (
    CriteriaReconciliationService,
    ReconcileResult,
)
from app.schemas.criteria_manifest import Manifest, MANIFEST_SCHEMA_VERSION


def _empty_manifest():
    from datetime import datetime, timezone

    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        generated_at=datetime.now(tz=timezone.utc),
        criteria=[],
    )


@pytest.mark.asyncio
async def test_skips_when_hash_unchanged_and_state_ok():
    pytest.skip("Wave 7: replaced by v2 alias-map reconcile (see tests/test_criteria_reconciliation_v2.py)")
    app_state = AsyncMock()
    app_state.get = AsyncMock(
        side_effect=lambda k: {
            KEY_API_KEY_HASH: "samehash",
            KEY_SYNC_STATE: SYNC_STATE_OK,
        }[k]
    )
    manifest_svc = AsyncMock()
    criteria_repo = AsyncMock()
    vector_svc = AsyncMock()

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="key",
    )
    with patch.object(svc, "_hash_key", return_value="samehash"):
        result = await svc.reconcile()
    assert result.skipped is True


@pytest.mark.asyncio
async def test_wipes_and_repopulates_on_key_change():
    pytest.skip("Wave 7: replaced by v2 alias-map reconcile (see tests/test_criteria_reconciliation_v2.py)")
    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value="oldhash")
    app_state.set_many = AsyncMock()

    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(return_value=_empty_manifest())
    manifest_svc.upload = AsyncMock()

    criteria_repo = AsyncMock()
    criteria_repo.truncate = AsyncMock()
    criteria_repo.bulk_insert = AsyncMock()

    vector_svc = AsyncMock()
    vector_svc.list_document_ids = AsyncMock(return_value=[])

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="newkey",
    )

    with patch.object(svc, "_wipe_upload_dir"):
        result = await svc.reconcile()

    assert result.ok is True
    criteria_repo.truncate.assert_awaited()
    app_state.set_many.assert_awaited()


@pytest.mark.asyncio
async def test_cloud_unavailable_with_key_change_wipes_and_sets_error():
    pytest.skip("Wave 7: replaced by v2 alias-map reconcile (see tests/test_criteria_reconciliation_v2.py)")
    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value="oldhash")
    app_state.set_many = AsyncMock()

    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(side_effect=CloudUnavailable("net"))

    criteria_repo = AsyncMock()
    criteria_repo.truncate = AsyncMock()
    vector_svc = AsyncMock()

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="newkey",
    )

    with patch.object(svc, "_wipe_upload_dir"):
        result = await svc.reconcile()

    assert result.ok is False
    criteria_repo.truncate.assert_awaited()
    args, _ = app_state.set_many.call_args
    assert args[0][KEY_SYNC_STATE] == "error"


@pytest.mark.asyncio
async def test_cloud_unavailable_with_key_change_preserves_db_when_wipe_fails():
    pytest.skip("Wave 7: replaced by v2 alias-map reconcile (see tests/test_criteria_reconciliation_v2.py)")
    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value="oldhash")
    app_state.set_many = AsyncMock()

    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(side_effect=CloudUnavailable("net"))

    criteria_repo = AsyncMock()
    criteria_repo.truncate = AsyncMock()
    vector_svc = AsyncMock()

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="newkey",
    )

    with patch.object(
        svc, "_wipe_upload_dir", side_effect=RuntimeError("permission denied")
    ):
        result = await svc.reconcile()

    assert result.ok is False
    assert "wipe also failed" in result.error
    criteria_repo.truncate.assert_not_awaited()
    args, _ = app_state.set_many.call_args
    assert args[0][KEY_SYNC_STATE] == "error"
    assert "permission denied" in args[0][KEY_SYNC_ERROR]


@pytest.mark.asyncio
async def test_cloud_unavailable_without_key_change_marks_needs_resync():
    pytest.skip("Wave 7: replaced by v2 alias-map reconcile (see tests/test_criteria_reconciliation_v2.py)")
    app_state = AsyncMock()
    app_state.get = AsyncMock(
        side_effect=lambda k: {
            KEY_API_KEY_HASH: "samehash",
            KEY_SYNC_STATE: "needs_resync",
        }[k]
    )
    app_state.set = AsyncMock()
    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(side_effect=CloudUnavailable("net"))
    criteria_repo = AsyncMock()
    vector_svc = AsyncMock()

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="key",
    )
    with patch.object(svc, "_hash_key", return_value="samehash"):
        result = await svc.reconcile()
    assert result.ok is False
    criteria_repo.truncate.assert_not_awaited()


@pytest.mark.asyncio
async def test_lock_serializes_concurrent_calls():
    pytest.skip("Wave 7: replaced by v2 alias-map reconcile (see tests/test_criteria_reconciliation_v2.py)")
    import asyncio
    import time

    timestamps: list[tuple[float, float]] = []

    async def slow_truncate():
        start = time.monotonic()
        await asyncio.sleep(0.05)
        end = time.monotonic()
        timestamps.append((start, end))

    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value=None)
    app_state.set_many = AsyncMock()

    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(return_value=_empty_manifest())
    criteria_repo = AsyncMock()
    criteria_repo.truncate = AsyncMock(side_effect=slow_truncate)
    criteria_repo.bulk_insert = AsyncMock()
    vector_svc = AsyncMock()
    vector_svc.list_document_ids = AsyncMock(return_value=[])

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="k",
    )

    with patch.object(svc, "_wipe_upload_dir"):
        await asyncio.gather(svc.reconcile(), svc.reconcile())

    assert len(timestamps) == 2
    # 두 truncate가 겹치지 않아야 함
    timestamps.sort()
    assert timestamps[0][1] <= timestamps[1][0] + 0.01, \
        f"reconcile calls overlapped: {timestamps}"


@pytest.mark.asyncio
async def test_reconcile_inserts_synthetic_required_fields_for_cloud_entries():
    pytest.skip("Wave 7: replaced by v2 alias-map reconcile (see tests/test_criteria_reconciliation_v2.py)")
    from datetime import datetime, timezone
    from app.schemas.criteria_manifest import (
        Manifest, ManifestEntry, MANIFEST_SCHEMA_VERSION,
    )

    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value="oldhash")
    app_state.set_many = AsyncMock()

    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(return_value=Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        generated_at=datetime.now(tz=timezone.utc),
        criteria=[ManifestEntry(
            document_id="files/abc",
            title="rubric.pdf",
            display_alias=None,
            status="active",
        )],
    ))

    criteria_repo = AsyncMock()
    criteria_repo.truncate = AsyncMock()
    criteria_repo.bulk_insert = AsyncMock()

    vector_svc = AsyncMock()
    vector_svc.list_document_ids = AsyncMock(return_value=["files/abc"])

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="newkey",
    )
    with patch.object(svc, "_wipe_upload_dir"):
        result = await svc.reconcile()

    assert result.ok is True
    rows = criteria_repo.bulk_insert.call_args[0][0]
    assert len(rows) == 1
    assert rows[0]["file_size"] == 0
    assert rows[0]["uploaded_by"] == "<cloud-sync>"
    assert rows[0]["file_path"] == "files/abc"
