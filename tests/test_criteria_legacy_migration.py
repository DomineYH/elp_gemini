"""legacy migration: manifest → alias_map + metadata-store 삭제"""
import hashlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.alias_map import AliasMap, AliasMapEntry


def _doc_kv(name, kv_pairs):
    return {
        "document_id": name,
        "display_name": "x",
        "custom_metadata_kv": {k: (v, []) for k, v in kv_pairs},
    }


async def _reconcile_with_cloud_docs(docs, alias_entries=None):
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    fake_client = MagicMock()
    fake_vec = MagicMock()
    fake_vec.file_search_service.client = fake_client
    fake_vec.list_criteria_documents = AsyncMock(return_value=docs)

    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(return_value=(
        "docs/alias-map",
        AliasMap(
            schema_version=1,
            updated_at="2026-05-15T00:00:00Z",
            entries=alias_entries or {},
        ),
    ))
    fake_alias.replace = AsyncMock()

    inserted = []
    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()
    fake_repo.delete_by_stable_ids_except = AsyncMock()

    async def _upsert_from_cloud(**kwargs):
        inserted.append(kwargs)

    fake_repo.upsert_from_cloud = _upsert_from_cloud
    fake_repo.get_criteria_by_stable_id = AsyncMock(return_value=None)

    state_values = {
        "criteria_api_key_hash": "samehash",
        "criteria_sync_state": "needs_resync",
        "criteria_migration_v2_done": "true",
    }
    fake_state = MagicMock()
    fake_state.get = AsyncMock(side_effect=lambda key: state_values.get(key))
    fake_state.set_many = AsyncMock(side_effect=state_values.update)
    fake_state.set = AsyncMock()

    db = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    from unittest.mock import patch

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

    return SimpleNamespace(result=result, alias=fake_alias, inserted=inserted)


@pytest.mark.asyncio
async def test_no_op_when_migration_marker_set():
    from app.services.criteria_legacy_migration import migrate_from_legacy_manifest

    state = MagicMock()
    state.get = AsyncMock(return_value="true")  # marker present
    client = MagicMock()
    state.set = AsyncMock()

    await migrate_from_legacy_manifest(client=client, app_state=state)

    client.file_search_stores.list.assert_not_called()


@pytest.mark.asyncio
async def test_no_op_when_legacy_store_absent():
    from app.services.criteria_legacy_migration import migrate_from_legacy_manifest

    state = MagicMock()
    state.get = AsyncMock(return_value=None)
    state.set = AsyncMock()

    client = MagicMock()
    rubric_store = MagicMock()
    rubric_store.name = "stores/r"
    rubric_store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([rubric_store])

    await migrate_from_legacy_manifest(client=client, app_state=state)

    state.set.assert_called_once_with("criteria_migration_v2_done", "true")


@pytest.mark.asyncio
async def test_deletes_legacy_store_and_sets_marker():
    from app.services.criteria_legacy_migration import migrate_from_legacy_manifest

    state = MagicMock()
    state.get = AsyncMock(return_value=None)
    state.set = AsyncMock()

    legacy_store = MagicMock()
    legacy_store.name = "stores/legacy"
    legacy_store.display_name = "rubric-metadata-store"
    rubric_store = MagicMock()
    rubric_store.name = "stores/r"
    rubric_store.display_name = "rubric-store"

    client = MagicMock()
    client.file_search_stores.list.return_value = iter([rubric_store, legacy_store])
    client.file_search_stores.delete = MagicMock()

    await migrate_from_legacy_manifest(client=client, app_state=state)

    client.file_search_stores.delete.assert_called_once_with(
        name="stores/legacy", config={"force": True}
    )
    state.set.assert_called_once_with("criteria_migration_v2_done", "true")


@pytest.mark.asyncio
async def test_reconcile_uses_legacy_surrogates_for_legacy_docs_without_stable_id(
    caplog,
):
    caplog.set_level(
        logging.WARNING,
        logger="app.services.criteria_reconciliation_service",
    )
    doc_ids = [
        "fileSearchStores/s/documents/a",
        "fileSearchStores/s/documents/b",
    ]
    surrogate_ids = [
        "legacy_" + hashlib.sha1(doc_id.encode("utf-8")).hexdigest()[:16]
        for doc_id in doc_ids
    ]
    outcome = await _reconcile_with_cloud_docs([
        _doc_kv(doc_ids[0], [
            ("type", "criteria"),
            ("original_title_b64", "Zmlyc3Q="),
        ]),
        _doc_kv(doc_ids[1], [
            ("type", "criteria"),
            ("original_title_b64", "c2Vjb25k"),
        ]),
    ])

    assert outcome.result.ok is True
    outcome.alias.replace.assert_called_once()
    healed_map = outcome.alias.replace.call_args.args[0]
    assert set(healed_map.entries) == set(surrogate_ids)
    assert [row["stable_id"] for row in outcome.inserted] == surrogate_ids
    assert [row["document_id"] for row in outcome.inserted] == doc_ids
    assert all(
        entry.alias is None and entry.status == "uploaded"
        for entry in healed_map.entries.values()
    )
    assert doc_ids[0] in caplog.text
    assert doc_ids[1] in caplog.text
    assert "migrated without proper stable_id" in caplog.text


@pytest.mark.asyncio
async def test_reconcile_preserves_mixed_stable_and_surrogate_documents():
    stable_id = "01HSTABLE"
    legacy_document_id = "fileSearchStores/s/documents/legacy"
    surrogate_id = (
        "legacy_"
        + hashlib.sha1(legacy_document_id.encode("utf-8")).hexdigest()[:16]
    )
    outcome = await _reconcile_with_cloud_docs(
        [
            _doc_kv("fileSearchStores/s/documents/modern", [
                ("type", "criteria"),
                ("stable_id", stable_id),
            ]),
            _doc_kv(legacy_document_id, [("type", "criteria")]),
        ],
        alias_entries={
            stable_id: AliasMapEntry(
                alias="existing",
                status="active",
                activated_at="2026-05-15T00:00:00Z",
            ),
        },
    )

    assert outcome.result.ok is True
    outcome.alias.replace.assert_called_once()
    healed_map = outcome.alias.replace.call_args.args[0]
    assert set(healed_map.entries) == {stable_id, surrogate_id}
    assert healed_map.entries[stable_id].alias == "existing"
    assert healed_map.entries[stable_id].status == "active"
    assert healed_map.entries[surrogate_id].alias is None
    assert healed_map.entries[surrogate_id].status == "uploaded"
    assert {row["stable_id"] for row in outcome.inserted} == {
        stable_id,
        surrogate_id,
    }


@pytest.mark.asyncio
async def test_reconcile_fresh_install_stable_id_documents_do_not_use_surrogates(
    caplog,
):
    caplog.set_level(
        logging.WARNING,
        logger="app.services.criteria_reconciliation_service",
    )
    doc_ids = [
        "fileSearchStores/s/documents/modern-a",
        "fileSearchStores/s/documents/modern-b",
    ]
    stable_ids = ["01HAAA", "01HBBB"]
    outcome = await _reconcile_with_cloud_docs([
        _doc_kv(doc_ids[0], [
            ("type", "criteria"),
            ("stable_id", stable_ids[0]),
        ]),
        _doc_kv(doc_ids[1], [
            ("type", "criteria"),
            ("stable_id", stable_ids[1]),
        ]),
    ])

    assert outcome.result.ok is True
    healed_map = outcome.alias.replace.call_args.args[0]
    assert set(healed_map.entries) == set(stable_ids)
    assert set(healed_map.entries).isdisjoint(doc_ids)
    assert {row["stable_id"] for row in outcome.inserted} == set(stable_ids)
    assert "migrated without proper stable_id" not in caplog.text
