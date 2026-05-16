"""reconcile v2 — alias_map 기반"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.app_state import AppState  # noqa: F401
from app.models.criteria import Criteria  # noqa: F401
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_API_KEY_HASH,
    KEY_SYNC_STATE,
)
from app.repositories.criteria_repository import CriteriaRepository
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


@pytest.mark.asyncio
async def test_reconcile_with_real_session_after_state_reads_rebuilds_cache():
    """state 조회가 실제 AsyncSession 트랜잭션을 시작해도 reconcile이 완료된다."""
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as db:
        state_repo = AppStateRepository(db)
        await state_repo.set_many({
            KEY_API_KEY_HASH: "samehash",
            KEY_SYNC_STATE: "needs_resync",
        })
        await db.commit()

        fake_vec = MagicMock()
        fake_vec.file_search_service.client.file_search_stores.list.return_value = (
            []
        )
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
                        alias="1학기",
                        status="active",
                        activated_at="2026-05-15T00:00:00Z",
                    ),
                },
            ),
        ))
        fake_alias.replace = AsyncMock()

        with patch(
            "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
            return_value="samehash",
        ):
            svc = CriteriaReconciliationService(
                db=db,
                vector_service=fake_vec,
                alias_map_service=fake_alias,
                criteria_repo=CriteriaRepository(db),
                app_state_repo=state_repo,
            )
            result = await svc.reconcile()

        assert result.ok is True
        assert result.error is None
        assert await state_repo.get(KEY_SYNC_STATE) == "ok"

        row = await CriteriaRepository(db).get_criteria_by_stable_id("01HA")
        assert row is not None
        assert row.document_id == "docs/a"

    await engine.dispose()
