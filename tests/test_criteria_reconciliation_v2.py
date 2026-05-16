"""reconcile v2 — alias_map 기반"""
import asyncio
import hashlib
import logging
import re
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import errors as genai_errors
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.schemas.alias_map import AliasMap, AliasMapEntry


def _doc_kv(name, kv_pairs):
    """kv_pairs: list of (key, string_value)"""
    return {
        "document_id": name,
        "display_name": "x",
        "custom_metadata_kv": {k: (v, []) for k, v in kv_pairs},
    }


async def _keep_loop_awake():
    while True:
        await asyncio.sleep(0.01)


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

    async def _insert(**kwargs):
        inserted.append(kwargs)

    fake_repo.insert = _insert

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

    return SimpleNamespace(
        result=result,
        alias=fake_alias,
        inserted=inserted,
    )


def test_kv_string_joins_string_list_metadata_chunks():
    from app.services.criteria_reconciliation_service import _kv_string

    doc = {
        "custom_metadata_kv": {
            "original_title_b64": (None, ["7ZWc6riA", "IO2PieqwgA=="]),
        },
    }

    assert _kv_string(doc, "original_title_b64") == "7ZWc6riAIO2PieqwgA=="


def test_legacy_surrogate_stable_id_is_url_safe_and_deterministic():
    from app.services.criteria_reconciliation_service import (
        legacy_surrogate_stable_id,
    )

    document_id = "fileSearchStores/s/documents/pre-v2-rubric"

    first = legacy_surrogate_stable_id(document_id)
    second = legacy_surrogate_stable_id(document_id)

    assert first == second
    assert first == (
        "legacy_"
        + hashlib.sha1(document_id.encode("utf-8")).hexdigest()[:16]
    )
    assert re.fullmatch(r"legacy_[a-f0-9]{16}", first)


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
async def test_reconcile_upgrade_ok_state_with_real_session_completes():
    """migration marker read must not autobegin before later explicit begin()."""
    from app.db import Base
    from app.models import app_state as _app_state_model  # noqa: F401
    from app.models import criteria as _criteria_model  # noqa: F401
    from app.repositories.app_state_repository import (
        AppStateRepository,
        KEY_API_KEY_HASH,
        KEY_SYNC_STATE,
    )
    from app.repositories.criteria_repository import CriteriaRepository
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ticker = asyncio.create_task(_keep_loop_awake())
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            state = AppStateRepository(db)
            async with db.begin():
                await state.set(KEY_API_KEY_HASH, "samehash")
                await state.set(KEY_SYNC_STATE, "ok")

        fake_client = MagicMock()
        fake_client.file_search_stores.list.return_value = iter([])
        fake_vec = MagicMock()
        fake_vec.file_search_service.client = fake_client
        fake_vec.list_criteria_documents = AsyncMock(return_value=[
            _doc_kv("fileSearchStores/s/documents/a", [
                ("type", "criteria"),
                ("stable_id", "01HA"),
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
                        alias=None, status="uploaded", activated_at=None,
                    ),
                },
            ),
        ))
        fake_alias.replace = AsyncMock()

        async with session_factory() as db:
            with patch(
                "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
                return_value="samehash",
            ):
                svc = CriteriaReconciliationService(
                    db=db,
                    vector_service=fake_vec,
                    alias_map_service=fake_alias,
                    criteria_repo=CriteriaRepository(db),
                    app_state_repo=AppStateRepository(db),
                )
                result = await svc.reconcile()

        assert result.ok is True
        assert result.error is None
        assert result.count == 1
    finally:
        await engine.dispose()
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker


@pytest.mark.asyncio
async def test_reconcile_completes_when_session_already_autobegun():
    """Manual admin route reuses a session already touched by admin auth."""
    from app.db import Base
    from app.models import app_state as _app_state_model  # noqa: F401
    from app.models import criteria as _criteria_model  # noqa: F401
    from app.models.app_state import AppState
    from app.repositories.app_state_repository import (
        AppStateRepository,
        KEY_API_KEY_HASH,
        KEY_SYNC_STATE,
    )
    from app.repositories.criteria_repository import CriteriaRepository
    from app.services.criteria_legacy_migration import MIGRATION_MARKER_KEY
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ticker = asyncio.create_task(_keep_loop_awake())
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            state = AppStateRepository(db)
            async with db.begin():
                await state.set(KEY_API_KEY_HASH, "samehash")
                await state.set(KEY_SYNC_STATE, "needs_resync")
                await state.set(MIGRATION_MARKER_KEY, "true")

        fake_client = MagicMock()
        fake_client.file_search_stores.list.return_value = iter([])
        fake_vec = MagicMock()
        fake_vec.file_search_service.client = fake_client
        fake_vec.list_criteria_documents = AsyncMock(return_value=[
            _doc_kv("fileSearchStores/s/documents/a", [
                ("type", "criteria"),
                ("stable_id", "01HA"),
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
                        alias=None, status="uploaded", activated_at=None,
                    ),
                },
            ),
        ))
        fake_alias.replace = AsyncMock()

        async with session_factory() as db:
            await db.execute(
                select(AppState).where(AppState.key == KEY_SYNC_STATE)
            )
            assert db.in_transaction() is True

            with patch(
                "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
                return_value="samehash",
            ):
                svc = CriteriaReconciliationService(
                    db=db,
                    vector_service=fake_vec,
                    alias_map_service=fake_alias,
                    criteria_repo=CriteriaRepository(db),
                    app_state_repo=AppStateRepository(db),
                )
                result = await svc.reconcile()

        assert result.ok is True
        assert result.error is None
        assert result.count == 1
    finally:
        await engine.dispose()
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker


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
async def test_reconcile_uses_legacy_surrogates_for_missing_stable_ids(
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


@pytest.mark.asyncio
async def test_reconcile_demotes_active_legacy_surrogates():
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
                alias=None,
                status="active",
                activated_at="2026-05-15T00:00:00Z",
            ),
            surrogate_id: AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-16T00:00:00Z",
            ),
        },
    )

    assert outcome.result.ok is True
    outcome.alias.replace.assert_called_once()
    healed_map = outcome.alias.replace.call_args.args[0]
    assert healed_map.entries[stable_id].status == "active"
    assert healed_map.entries[surrogate_id].status == "uploaded"
    inserted_by_stable_id = {row["stable_id"]: row for row in outcome.inserted}
    assert inserted_by_stable_id[stable_id]["status"] == "active"
    assert inserted_by_stable_id[surrogate_id]["status"] == "uploaded"


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


@pytest.mark.asyncio
async def test_reconcile_completes_dbcache_after_chunk_size_fix():
    """Issue #60: pre-v2 docs force a multi-chunk alias_map upload. Before the
    fix, the upload failed with 400 INVALID_ARGUMENT (StringList > 256 chars)
    and reconcile bailed out before populating the local criteria cache, so
    the admin UI showed no criteria. After the fix, reconcile must reach the
    insert step and the alias_map service must receive entries for every
    pre-v2 doc.
    """
    docs = [
        _doc_kv(
            "fileSearchStores/rs/docs/pdf-xdo2amdu4xih",
            [("type", "criteria")],
        ),
        _doc_kv(
            "fileSearchStores/rs/docs/2022pdf-pbdczm0207y6",
            [("type", "criteria")],
        ),
    ]

    # Mirror the real 256-char API limit inside the alias_map replace call so
    # this test fails if the chunk-size constant regresses.
    from app.services import alias_map_codec
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    observed_chunk_counts = []

    def _enforcing_replace(alias_map, old_doc_name=None):
        chunks = alias_map_codec.encode_alias_map_payload(
            alias_map.model_dump(mode="json")
        )
        observed_chunk_counts.append(len(chunks))
        longest = max((len(c) for c in chunks), default=0)
        if longest > 256:
            raise genai_errors.ClientError(
                400,
                {"error": {
                    "code": 400,
                    "status": "INVALID_ARGUMENT",
                    "message": (
                        "* UploadToFileSearchStoreRequest."
                        "custom_metadata[1].string_list_value.values[0]: "
                        "StringList value cannot be more than 256 characters "
                        "long."
                    ),
                }},
            )
        return "fileSearchStores/rs/docs/alias-map-new"

    fake_client = MagicMock()
    fake_vec = MagicMock()
    fake_vec.file_search_service.client = fake_client
    fake_vec.list_criteria_documents = AsyncMock(return_value=docs)

    fake_alias = MagicMock()
    # Start from no existing alias_map so reconcile synthesises both entries.
    fake_alias.fetch = AsyncMock(return_value=None)
    fake_alias.replace = AsyncMock(side_effect=_enforcing_replace)

    inserted = []
    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()

    async def _insert(**kwargs):
        inserted.append(kwargs)

    fake_repo.insert = _insert

    state_values = {"criteria_sync_state": "needs_resync"}
    fake_state = MagicMock()
    fake_state.get = AsyncMock(side_effect=lambda key: state_values.get(key))
    fake_state.set_many = AsyncMock(side_effect=state_values.update)
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

    # Reconcile completed successfully.
    assert result.ok is True, f"reconcile failed: error={result.error}"
    assert result.error is None
    assert result.count == 2

    # alias_map.replace was called with one entry per pre-v2 doc.
    fake_alias.replace.assert_awaited_once()
    sent_alias_map: AliasMap = fake_alias.replace.await_args.args[0]
    assert len(sent_alias_map.entries) == 2
    assert observed_chunk_counts and observed_chunk_counts[0] > 1

    # Local cache was rebuilt: both legacy-surrogate stable_ids inserted.
    assert len(inserted) == 2
    surrogate_ids = sorted(row["stable_id"] for row in inserted)
    assert all(sid.startswith("legacy_") for sid in surrogate_ids), surrogate_ids

    # Sync state was advanced to ok (not stuck on needs_resync).
    assert state_values.get("criteria_sync_state") == "ok"
