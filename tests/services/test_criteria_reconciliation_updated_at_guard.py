"""Tests for Issue #80 — cloud alias_map.updated_at 기반 reconcile guard."""

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


def _make_service(state_values, alias_map, list_docs):
    state = MagicMock()

    async def _get(key):
        return state_values.get(key)

    async def _set_many(items):
        state_values.update(items)

    state.get = AsyncMock(side_effect=_get)
    state.set_many = AsyncMock(side_effect=_set_many)

    alias = MagicMock()
    alias.fetch = AsyncMock(return_value=("doc/1", alias_map))
    alias.replace = AsyncMock()

    vec = MagicMock()
    vec.list_criteria_documents = AsyncMock(return_value=list_docs)

    repo = MagicMock()
    repo.truncate = AsyncMock()
    repo.insert = AsyncMock()
    repo.get_criteria_by_stable_id = AsyncMock(return_value=None)

    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    db.begin = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock()
    db.begin.return_value.__aexit__ = AsyncMock()

    return CriteriaReconciliationService(
        db=db,
        vector_service=vec,
        alias_map_service=alias,
        criteria_repo=repo,
        app_state_repo=state,
    ), vec, alias, repo


def test_key_last_alias_map_updated_at_constant_exists():
    from app.repositories.app_state_repository import (
        KEY_LAST_ALIAS_MAP_UPDATED_AT,
    )
    assert KEY_LAST_ALIAS_MAP_UPDATED_AT == "criteria_last_alias_map_updated_at"


@pytest.mark.asyncio
async def test_reconcile_skips_when_cloud_updated_at_matches_stored():
    """가드 핵심 분기 — cloud의 updated_at이 stored와 같으면 list_criteria_documents 호출 없이 skip."""
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-26T00:00:00Z",
        entries={
            "sid_a": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-26T00:00:00Z",
            ),
        },
    )
    state_values = {
        KEY_API_KEY_HASH: sha256_hex_of_api_key(),
        KEY_SYNC_STATE: "ok",
        "criteria_migration_v2_done": "true",
        KEY_LAST_ALIAS_MAP_UPDATED_AT: "2026-05-26T00:00:00Z",
    }
    svc, vec, alias, repo = _make_service(state_values, alias_map, [])

    result = await svc.reconcile()

    assert result.skipped is True
    alias.fetch.assert_awaited_once()
    vec.list_criteria_documents.assert_not_awaited()
    repo.truncate.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_proceeds_when_cloud_updated_at_differs():
    """다른 인스턴스가 cloud를 갱신해 updated_at이 stored와 다르면 reconcile이 진행되어야 한다."""
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-26T01:00:00Z",  # cloud는 더 새 버전
        entries={
            "sid_a": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-26T01:00:00Z",
            ),
        },
    )
    state_values = {
        KEY_API_KEY_HASH: sha256_hex_of_api_key(),
        KEY_SYNC_STATE: "ok",
        "criteria_migration_v2_done": "true",
        KEY_LAST_ALIAS_MAP_UPDATED_AT: "2026-05-26T00:00:00Z",  # local은 옛 버전
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
    svc, vec, alias, repo = _make_service(state_values, alias_map, docs)

    result = await svc.reconcile()

    assert result.ok is True
    assert result.skipped is False
    vec.list_criteria_documents.assert_awaited()
    # set_many에 새 updated_at이 기록되어야 한다
    assert state_values[KEY_LAST_ALIAS_MAP_UPDATED_AT] == "2026-05-26T01:00:00Z"


@pytest.mark.asyncio
async def test_reconcile_proceeds_on_first_run_when_stored_updated_at_missing():
    """stored가 비어 있는 최초 reconcile은 skip 분기를 우회해야 한다."""
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-26T00:00:00Z",
        entries={},
    )
    state_values = {
        KEY_API_KEY_HASH: sha256_hex_of_api_key(),
        KEY_SYNC_STATE: "ok",
        "criteria_migration_v2_done": "true",
        # KEY_LAST_ALIAS_MAP_UPDATED_AT 부재
    }
    svc, vec, alias, repo = _make_service(state_values, alias_map, [])

    result = await svc.reconcile()

    # skip 가드가 stored_alias_updated_at is None 시에는 발동하지 않으므로 진행
    assert result.skipped is False
