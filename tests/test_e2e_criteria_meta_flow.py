"""
End-to-end smoke for criteria-cloud-metadata feature.

Covers: upload → activate → patch alias → delete → reconcile under mocked SDK.

This is a scaffold; full integration coverage lives in service-level tests
across Waves 2-5. This file documents the happy path and serves as the
canonical example of how the new flow composes.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.alias_map import AliasMap, AliasMapEntry, empty_alias_map


@pytest.mark.asyncio
async def test_round_trip_documented_for_future_implementation():
    """
    Behavioral expectations for the full flow:

    1. Boot app with empty alias_map.
    2. Upload PDF (POST /api/admin/criteria/upload):
       - CriteriaVectorService.upload_criteria called with stable_id + title
       - alias_map gains entry {alias:None, status:"uploaded"}
       - DB row created with matching stable_id
    3. Activate (POST /api/admin/criteria/{stable_id}/activate):
       - alias_map entry status becomes "active"
       - DB row status becomes "active"
    4. Patch alias (PATCH /api/admin/criteria/{stable_id}/alias):
       - alias_map entry alias updated (PDF NOT re-uploaded)
       - DB row display_alias updated
    5. Delete (DELETE /api/admin/criteria/{stable_id}):
       - documents.delete(name=document_id) called
       - alias_map entry removed
       - DB row removed
    6. Reconcile with simulated API key change:
       - DB wiped; rebuilt from cloud (now empty)
       - app_state.criteria_api_key_hash updated to new hash

    This skeleton is left as documentation; the per-step assertions
    are covered by service-level tests in Wave 2-5 (see:
    - tests/test_criteria_vector_service_upload_metadata.py
    - tests/test_criteria_alias_map_service_replace.py
    - tests/test_criteria_reconciliation_v2.py
    - tests/test_admin_criteria_*.py
    )
    """
    pytest.skip(
        "Scaffold — see service-level Wave 2-5 tests for component coverage. "
        "Full TestClient-based e2e to be added if/when admin auth fixture stabilizes."
    )


def test_feature_branch_modules_all_importable():
    """Smoke: every new module in the feature branch imports without error."""
    from app.schemas.alias_map import AliasMap, AliasMapEntry, empty_alias_map  # noqa: F401
    from app.services.alias_map_codec import (  # noqa: F401
        ALIAS_MAP_PAYLOAD_KEY,
        encode_alias_map_payload,
        decode_alias_map_payload,
    )
    from app.services.criteria_alias_map_service import CriteriaAliasMapService  # noqa: F401
    from app.services.criteria_legacy_migration import (  # noqa: F401
        migrate_from_legacy_manifest,
        LEGACY_METADATA_STORE_NAME,
        MIGRATION_MARKER_KEY,
    )
    from app.services.criteria_reconciliation_service import (  # noqa: F401
        CriteriaReconciliationService,
        ReconcileResult,
        sha256_hex_of_api_key,
    )
    from app.services.criteria_vector_service import CriteriaVectorService  # noqa: F401
    from app.migrations.criteria_stable_id import ensure_criteria_stable_id_column  # noqa: F401
    from app.repositories.criteria_repository import CriteriaRepository  # noqa: F401
    from app.models.criteria import Criteria

    # Spot check the column exists on the ORM model
    assert "stable_id" in Criteria.__table__.columns


def test_alias_map_pydantic_round_trip():
    """Sanity round-trip with the new schemas."""
    m = AliasMap(
        schema_version=1,
        updated_at="2026-05-15T00:00:00Z",
        entries={
            "01HXYZ": AliasMapEntry(alias="1학기", status="active", activated_at="2026-05-15T00:00:00Z"),
        },
    )
    raw = m.model_dump(mode="json")
    parsed = AliasMap.model_validate(raw)
    assert parsed.entries["01HXYZ"].alias == "1학기"
