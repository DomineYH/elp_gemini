"""E2E: 다중 active 평가기준 라이프사이클 회귀.

Mocks Gemini File Search client; exercises real DB + alias_map + router stack.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.app_state_repository import (
    KEY_API_KEY_HASH,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_STATE,
)
from app.repositories.criteria_repository import CriteriaRepository
from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_reconciliation_service import legacy_surrogate_stable_id
from app.services.criteria_vector_service import CriteriaVectorService


def _criteria_doc(document_id, stable_id, display_name=None):
    """Build a fake criteria document dict for list_criteria_documents."""
    kv = {"type": ("criteria", [])}
    if stable_id:
        kv["stable_id"] = (stable_id, [])
    return {
        "document_id": document_id,
        "display_name": display_name or stable_id or document_id,
        "custom_metadata_kv": kv,
    }


def _patch_reconcile_services(fake_vector, fake_alias):
    """Patch both router-level and source-level for reconcile endpoint."""
    return (
        patch(
            "app.routers.admin.criteria.CriteriaVectorService",
            return_value=fake_vector,
        ),
        patch(
            "app.services.criteria_alias_map_service.CriteriaAliasMapService",
            return_value=fake_alias,
        ),
    )


@pytest.mark.asyncio
async def test_reconcile_promotes_all_cloud_criteria_to_active(
    e2e_client, fake_vector_client, db_session
):
    """key change → reconcile → all 3 cloud criteria become status=active."""
    fake_vector_client.list_criteria_documents = AsyncMock(return_value=[
        _criteria_doc("doc-1", "sid_a", "Criteria A"),
        _criteria_doc("doc-2", "sid_b", "Criteria B"),
        _criteria_doc("doc-3", "sid_c", "Criteria C"),
    ])

    fake_alias_svc = MagicMock()
    fake_alias_svc.fetch = AsyncMock(return_value=None)
    fake_alias_svc.replace = AsyncMock()

    p1, p2 = _patch_reconcile_services(fake_vector_client, fake_alias_svc)
    with p1, p2:
        res = await e2e_client.post("/api/admin/criteria/reconcile")

    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["count"] == 3

    repo = CriteriaRepository(db_session)
    all_criteria = await repo.get_all_criteria()
    assert len(all_criteria) == 3
    for c in all_criteria:
        assert c.status == "active"
        assert c.activated_at is not None


@pytest.mark.asyncio
async def test_upload_after_reconcile_keeps_existing_actives(
    e2e_client, fake_vector_client, db_session
):
    """existing 2 active + new upload → 3 active."""
    # Phase 1: reconcile 2 criteria
    fake_vector_client.list_criteria_documents = AsyncMock(return_value=[
        _criteria_doc("doc-1", "sid_a", "Criteria A"),
        _criteria_doc("doc-2", "sid_b", "Criteria B"),
    ])

    alias_reconcile = MagicMock()
    alias_reconcile.fetch = AsyncMock(return_value=None)
    alias_reconcile.replace = AsyncMock()

    p1, p2 = _patch_reconcile_services(fake_vector_client, alias_reconcile)
    with p1, p2:
        res = await e2e_client.post("/api/admin/criteria/reconcile")
    assert res.status_code == 200
    assert res.json()["count"] == 2

    # Phase 2: upload 3rd criteria
    fake_vector_client.upload_criteria = AsyncMock(
        return_value={"document_id": "doc-3"},
    )

    alias_upload = MagicMock()
    alias_upload.fetch = AsyncMock(return_value=None)
    alias_upload.replace = AsyncMock()

    with (
        patch("app.routers.admin.criteria.FileValidator") as val_cls,
        patch(
            "app.routers.admin.criteria.CriteriaVectorService",
            return_value=fake_vector_client,
        ),
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService",
            return_value=alias_upload,
        ),
    ):
        val_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True},
        )
        files = {"file": ("rubric.pdf", b"%PDF-1.4 content", "application/pdf")}
        res = await e2e_client.post("/api/admin/criteria/upload", files=files)

    assert res.status_code == 201

    # Phase 3: verify all 3 active in DB
    repo = CriteriaRepository(db_session)
    all_criteria = await repo.get_all_criteria()
    assert len(all_criteria) == 3
    active = [c for c in all_criteria if c.status == "active"]
    assert len(active) == 3


@pytest.mark.asyncio
async def test_search_filter_uses_or_expression_for_multi_active(
    e2e_client, fake_vector_client, db_session
):
    """In multi-active state, metadata_filter == '(stable_id="X" OR stable_id="Y")'."""
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-17T00:00:00Z",
        entries={
            "sid_a": AliasMapEntry(
                alias=None, status="active",
                activated_at="2026-05-17T00:00:00Z",
            ),
            "sid_b": AliasMapEntry(
                alias=None, status="active",
                activated_at="2026-05-17T00:01:00Z",
            ),
        },
    )

    mock_alias_svc = MagicMock()
    mock_alias_svc.fetch = AsyncMock(return_value=("doc-name", alias_map))

    with patch(
        "app.services.criteria_alias_map_service.CriteriaAliasMapService",
        return_value=mock_alias_svc,
    ):
        result = await CriteriaVectorService.active_stable_id_filter(
            client=MagicMock(),
            store_display_name="test-store",
        )

    assert result == '(stable_id="sid_b" OR stable_id="sid_a")'


@pytest.mark.asyncio
async def test_reconcile_demotes_only_legacy_surrogate_actives(
    e2e_client, fake_vector_client, db_session
):
    """legacy active + real active → real preserved, legacy demoted."""
    legacy_doc = _criteria_doc("doc-old", None, "Old Criteria")
    real_doc = _criteria_doc("doc-new", "sid_real", "Real Criteria")

    fake_vector_client.list_criteria_documents = AsyncMock(
        return_value=[legacy_doc, real_doc],
    )

    legacy_sid = legacy_surrogate_stable_id("doc-old")

    existing_alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-17T00:00:00Z",
        entries={
            legacy_sid: AliasMapEntry(
                alias=None, status="active",
                activated_at="2026-05-17T00:00:00Z",
            ),
            "sid_real": AliasMapEntry(
                alias=None, status="active",
                activated_at="2026-05-17T00:01:00Z",
            ),
        },
    )

    fake_alias_svc = MagicMock()
    fake_alias_svc.fetch = AsyncMock(
        return_value=("doc-name", existing_alias_map),
    )
    fake_alias_svc.replace = AsyncMock()

    p1, p2 = _patch_reconcile_services(fake_vector_client, fake_alias_svc)
    with p1, p2:
        res = await e2e_client.post("/api/admin/criteria/reconcile")

    assert res.status_code == 200
    assert res.json()["ok"] is True

    repo = CriteriaRepository(db_session)
    all_criteria = await repo.get_all_criteria()
    by_sid = {c.stable_id: c for c in all_criteria}

    # Legacy demoted
    assert by_sid[legacy_sid].status == "uploaded"
    assert by_sid[legacy_sid].activated_at is None

    # Real stays active
    assert by_sid["sid_real"].status == "active"
    assert by_sid["sid_real"].activated_at is not None
