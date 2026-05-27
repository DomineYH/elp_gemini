"""Tests for Issue #80 — reconcile preserves local-only columns via upsert."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.app_state_repository import (
    KEY_API_KEY_HASH,
    KEY_LAST_ALIAS_MAP_UPDATED_AT,
    KEY_SYNC_STATE,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_reconciliation_service import (
    CriteriaReconciliationService,
    sha256_hex_of_api_key,
)


@pytest.mark.asyncio
async def test_reconcile_preserves_uploaded_by_for_existing_local_rows():
    """A 인스턴스가 자기 업로드 행의 uploaded_by="alice"를 cloud-rebuild에서 잃지 않아야 한다."""
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-26T01:00:00Z",
        entries={
            "sid_a": AliasMapEntry(
                alias=None, status="active", activated_at="2026-05-26T01:00:00Z"
            ),
        },
    )
    state_values = {
        KEY_API_KEY_HASH: sha256_hex_of_api_key(),
        KEY_SYNC_STATE: "ok",
        "criteria_migration_v2_done": "true",
        KEY_LAST_ALIAS_MAP_UPDATED_AT: "2026-05-26T00:00:00Z",  # 옛 버전
    }
    docs = [
        {
            "document_id": "doc/sid_a",
            "display_name": "criterion-a",
            "custom_metadata_kv": {
                "type": ("criteria", []),
                "stable_id": ("sid_a", []),
                "original_title_b64": (None, []),
                "created_at": ("2026-05-26T00:50:00Z", []),
            },
        },
    ]

    existing_row = MagicMock()
    existing_row.uploaded_by = "alice"
    existing_row.stable_id = "sid_a"
    existing_row.file_size = 12345
    existing_row.file_path = "/local/path/a.pdf"

    state = MagicMock()
    state.get = AsyncMock(side_effect=lambda k: state_values.get(k))
    state.set_many = AsyncMock(side_effect=lambda items: state_values.update(items))

    alias = MagicMock()
    alias.fetch = AsyncMock(return_value=("doc/alias", alias_map))
    alias.replace = AsyncMock()

    vec = MagicMock()
    vec.list_criteria_documents = AsyncMock(return_value=docs)

    repo = MagicMock()
    repo.truncate = AsyncMock()
    repo.upsert_from_cloud = AsyncMock()
    repo.delete_by_stable_ids_except = AsyncMock()
    repo.get_criteria_by_stable_id = AsyncMock(return_value=existing_row)

    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    db.begin = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock()
    db.begin.return_value.__aexit__ = AsyncMock()

    svc = CriteriaReconciliationService(
        db=db,
        vector_service=vec,
        alias_map_service=alias,
        criteria_repo=repo,
        app_state_repo=state,
    )

    result = await svc.reconcile()

    assert result.ok is True
    # truncate는 더 이상 호출되면 안 된다
    repo.truncate.assert_not_awaited()
    # upsert가 호출되었고 cloud-소스 필드만 전달되었는지 확인 (uploaded_by 미포함)
    repo.upsert_from_cloud.assert_awaited()
    call_kwargs = repo.upsert_from_cloud.await_args.kwargs
    assert "uploaded_by" not in call_kwargs
    assert call_kwargs["stable_id"] == "sid_a"
    # cloud에 없는 행을 삭제하는 메서드도 호출되었는지
    repo.delete_by_stable_ids_except.assert_awaited_once()
    args, _ = repo.delete_by_stable_ids_except.call_args
    assert args[0] == {"sid_a"}
