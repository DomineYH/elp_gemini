"""reconcile v2 — alias_map 기반"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.alias_map import AliasMap, AliasMapEntry


def _doc_kv(name, kv_pairs):
    """kv_pairs: list of (key, string_value)"""
    return {
        "document_id": name,
        "display_name": "x",
        "custom_metadata_kv": {k: (v, []) for k, v in kv_pairs},
    }


def test_kv_string_joins_string_list_metadata_chunks():
    from app.services.criteria_reconciliation_service import _kv_string

    doc = {
        "custom_metadata_kv": {
            "original_title_b64": (None, ["7ZWc6riA", "IO2PieqwgA=="]),
        },
    }

    assert _kv_string(doc, "original_title_b64") == "7ZWc6riAIO2PieqwgA=="


@pytest.mark.asyncio
async def test_reconcile_runs_v2_migration_before_skip_on_ok_state():
    from app.services.criteria_legacy_migration import MIGRATION_MARKER_KEY
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    client = MagicMock()
    client.file_search_stores.list.return_value = iter([])

    fake_vec = MagicMock()
    fake_vec.file_search_service.client = client
    fake_vec.list_criteria_documents = AsyncMock(return_value=[
        _doc_kv("docs/a", [
            ("type", "criteria"),
            ("stable_id", "01HA"),
            ("original_title_b64", "aGVsbG8="),
            ("created_at", "2026-05-15T00:00:00Z"),
        ]),
    ])

    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(return_value=None)
    fake_alias.replace = AsyncMock()

    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()

    async def _insert(**kwargs):
        pass

    fake_repo.insert = _insert

    state_values = {
        "criteria_api_key_hash": "samehash",
        "criteria_sync_state": "ok",
    }

    async def _get(key):
        return state_values.get(key)

    async def _set(key, value):
        state_values[key] = value

    async def _set_many(values):
        state_values.update(values)

    fake_state = MagicMock()
    fake_state.get = AsyncMock(side_effect=_get)
    fake_state.set = AsyncMock(side_effect=_set)
    fake_state.set_many = AsyncMock(side_effect=_set_many)

    db = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
        return_value="samehash",
    ):
        svc = CriteriaReconciliationService(
            db=db,
            vector_service=fake_vec,
            alias_map_service=fake_alias,
            criteria_repo=fake_repo,
            app_state_repo=fake_state,
        )
        first = await svc.reconcile()

        assert first.ok is True
        assert first.skipped is False
        assert state_values[MIGRATION_MARKER_KEY] == "true"
        client.file_search_stores.list.assert_called_once()
        fake_vec.list_criteria_documents.assert_called_once()
        fake_alias.replace.assert_called_once()
        fake_repo.truncate.assert_called_once()

        client.file_search_stores.list.reset_mock()
        fake_vec.list_criteria_documents.reset_mock()
        fake_alias.fetch.reset_mock()
        fake_alias.replace.reset_mock()
        fake_repo.truncate.reset_mock()

        second = await svc.reconcile()

    assert second.skipped is True
    client.file_search_stores.list.assert_not_called()
    fake_vec.list_criteria_documents.assert_not_called()
    fake_alias.fetch.assert_not_called()
    fake_alias.replace.assert_not_called()
    fake_repo.truncate.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_inserts_rows_with_alias_from_map(monkeypatch):
    """alias_map의 항목이 DB에 그대로 머티리얼라이즈"""
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    fake_vec = MagicMock()
    fake_vec.list_criteria_documents = AsyncMock(return_value=[
        _doc_kv("docs/a", [
            ("type", "criteria"),
            ("stable_id", "01HA"),
            ("original_title_b64", "aGVsbG8="),  # "hello"
            ("created_at", "2026-05-15T00:00:00Z"),
        ]),
    ])
    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(return_value=(
        "docs/alias-map",
        AliasMap(
            schema_version=1,
            updated_at="2026-05-15T00:00:00Z",
            entries={
                "01HA": AliasMapEntry(
                    alias="1학기",
                    status="active",
                    activated_at="2026-05-15T00:00:00Z",
                ),
            },
        ),
    ))
    fake_alias.replace = AsyncMock()

    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()
    inserted = []

    async def _insert(**kwargs):
        inserted.append(kwargs)

    fake_repo.insert = _insert

    fake_state = MagicMock()
    fake_state.get = AsyncMock(side_effect=lambda key: {
        "criteria_api_key_hash": "samehash",
        "criteria_sync_state": "needs_resync",
    }.get(key))
    fake_state.set_many = AsyncMock()
    fake_state.set = AsyncMock()

    db = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
        return_value="samehash",
    ):
        svc = CriteriaReconciliationService(
            db=db,
            vector_service=fake_vec,
            alias_map_service=fake_alias,
            criteria_repo=fake_repo,
            app_state_repo=fake_state,
        )
        result = await svc.reconcile()

    assert result.ok is True
    assert len(inserted) == 1
    assert inserted[0]["stable_id"] == "01HA"
    assert inserted[0]["display_alias"] == "1학기"
    assert inserted[0]["status"] == "active"
    fake_alias.replace.assert_not_called()  # alias_map already consistent


@pytest.mark.asyncio
async def test_reconcile_self_heals_orphan_entries():
    """alias_map에 있지만 클라우드에 없는 stable_id는 alias_map에서 제거"""
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    fake_vec = MagicMock()
    fake_vec.list_criteria_documents = AsyncMock(return_value=[
        _doc_kv("docs/a", [
            ("type", "criteria"),
            ("stable_id", "01HA"),
            ("original_title_b64", "aGVsbG8="),
            ("created_at", "2026-05-15T00:00:00Z"),
        ]),
    ])
    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(return_value=(
        "docs/alias-map",
        AliasMap(
            schema_version=1,
            updated_at="2026-05-15T00:00:00Z",
            entries={
                "01HA": AliasMapEntry(
                    alias="x", status="uploaded", activated_at=None,
                ),
                "01HGHOST": AliasMapEntry(
                    alias="orphan", status="uploaded", activated_at=None,
                ),
            },
        ),
    ))
    fake_alias.replace = AsyncMock()

    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()

    async def _insert(**kwargs):
        pass

    fake_repo.insert = _insert

    fake_state = MagicMock()
    fake_state.get = AsyncMock(return_value=None)
    fake_state.set_many = AsyncMock()
    fake_state.set = AsyncMock()

    db = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
        return_value="newhash",
    ):
        svc = CriteriaReconciliationService(
            db=db,
            vector_service=fake_vec,
            alias_map_service=fake_alias,
            criteria_repo=fake_repo,
            app_state_repo=fake_state,
        )
        result = await svc.reconcile()

    assert result.ok is True
    fake_alias.replace.assert_called_once()
    healed_map = fake_alias.replace.call_args.args[0]
    assert "01HGHOST" not in healed_map.entries
    assert "01HA" in healed_map.entries
