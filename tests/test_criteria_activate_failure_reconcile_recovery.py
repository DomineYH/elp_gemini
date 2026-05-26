"""
Diagnostic regression — 평가기준 활성/비활성 500 + reconcile 복구 양상

사용자 보고: 평가기준 활성/비활성 시 500 에러가 나오고 재동기화를 클릭하면
적용이 되는 경우가 있음.

코드 경로 분석:
- `app/routers/admin/criteria.py:686-691` `_set_status_by_stable_id`의 outer
  `except Exception` 분기에서 `_raise_criteria_mutation_failed` 호출 → 500.
- `cloud_write_started=True` (line 667) 분기에서 `_mark_criteria_needs_resync`
  호출 → `KEY_SYNC_STATE` 가 `needs_resync` 로 마킹 → UI에 재동기화 버튼 노출.
- `replace()` (`app/services/criteria_alias_map_service.py:197-250`) 는 새 doc
  업로드(60s polling) + 기존 doc 삭제로 구성. 어느 단계든 transient 클라우드
  오류(5xx, 인증, 네트워크, 폴링 timeout) 가능.

가설:
- H1 (cloud partial/full commit + response failure): replace()가 cloud에 새
  alias-map 을 commit 한 뒤(또는 polling timeout 으로 비동기 op 가 결국
  commit 된 뒤) 예외를 던진다. 사용자는 500 + 재동기화 버튼을 본다. 재동기화
  클릭 시 fetch() 는 새로 commit 된 alias_map 을 읽어 DB rebuild → 사용자의
  의도된 상태가 "적용됨". 사용자 표현 "있음" = 이 분기.
- H2 (cloud unchanged): replace() 가 cloud 변경 없이 실패. 재동기화 클릭 시
  fetch() 는 옛 상태를 읽고 cleaned == entries → cloud 쓰기 없음 + DB rebuild.
  DB 는 원래 상태를 유지하므로 "적용 안 됨". 사용자 표현 "있음" 의 반대 분기.

본 모듈은 두 가설을 분리해서 재현하는 mock-수준 통합 테스트를 제공한다.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.repositories.app_state_repository import (
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_STATE,
)
from app.routers.admin.criteria import (
    activate_by_stable_id,
    reconcile_criteria,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry


def _doc(document_id: str, stable_id: str, title_b64: str = "aGVsbG8="):
    return {
        "document_id": document_id,
        "display_name": title_b64,
        "custom_metadata_kv": {
            "type": ("criteria", []),
            "stable_id": (stable_id, []),
            "original_title_b64": (None, [title_b64]),
            "created_at": ("2026-05-15T00:00:00Z", []),
        },
    }


@pytest.mark.asyncio
async def test_activate_500_then_reconcile_recovers_when_cloud_partially_committed():
    """H1 — 사용자 양상 "재동기화로 적용됨" 분기.

    Phase 1: activate → replace() 예외 → 500 + needs_resync.
    Phase 2: reconcile → cloud(alias.fetch) 가 이미 active 상태를 반환 (replace
        가 cloud 에 commit 된 뒤 polling/네트워크 단계에서 예외를 던졌다는
        가정) → DB rebuild 가 active 로 insert → sync_state=ok.

    핵심: 두 단계 사이의 차이는 "cloud 가 commit 되었는가" 뿐이다. 이 mock 에서
    Phase 2 의 fetch 가 active 상태를 반환하는 것이 그 분기를 표현한다.
    """
    stable_id = "01HACTIVE"
    document_id = "fileSearchStores/s/documents/doc-active"

    # ---------- Phase 1: activate fails with replace exception ----------
    db1 = AsyncMock()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "docs/alias-map-old",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    stable_id: AliasMapEntry(
                        alias=None, status="uploaded", activated_at=None,
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock(
            side_effect=TimeoutError("alias-map upload timeout"),
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db1,
            )

        assert exc_info.value.status_code == 500
        alias.replace.assert_awaited_once()
        # cloud_write_started=True 분기 → needs_resync 마킹
        state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")

    # ---------- Phase 2: reconcile recovers because cloud committed ----------
    db2 = MagicMock()
    db2.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db2.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    fake_client = MagicMock()
    fake_vec = MagicMock()
    fake_vec.file_search_service.client = fake_client
    fake_vec.list_criteria_documents = AsyncMock(return_value=[
        _doc(document_id, stable_id),
    ])

    # cloud-truth: alias_map already shows the entry as active (the partial-
    # commit that occurred before the replace() call surfaced TimeoutError).
    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(return_value=(
        "docs/alias-map-new",
        AliasMap(
            schema_version=1,
            updated_at="2026-05-15T00:00:01Z",
            entries={
                stable_id: AliasMapEntry(
                    alias=None,
                    status="active",
                    activated_at="2026-05-15T00:00:01Z",
                ),
            },
        ),
    ))
    fake_alias.replace = AsyncMock()

    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()
    fake_repo.delete_by_stable_ids_except = AsyncMock()
    upserted: list[dict] = []

    async def _upsert_from_cloud(**kwargs):
        upserted.append(kwargs)

    fake_repo.upsert_from_cloud = _upsert_from_cloud
    fake_repo.get_criteria_by_stable_id = AsyncMock(return_value=None)

    state_values: dict[str, object] = {
        "criteria_api_key_hash": "samehash",
        "criteria_sync_state": "needs_resync",
        "criteria_migration_v2_done": "true",
    }
    fake_state = MagicMock()
    fake_state.get = AsyncMock(side_effect=lambda key: state_values.get(key))
    fake_state.set = AsyncMock(side_effect=lambda k, v: state_values.__setitem__(k, v))

    async def _set_many(values):
        state_values.update(values)

    fake_state.set_many = AsyncMock(side_effect=_set_many)

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService",
        return_value=fake_vec,
    ), patch(
        # reconcile_criteria 라우터는 함수 내부에서 local import 함
        "app.services.criteria_alias_map_service.CriteriaAliasMapService",
        return_value=fake_alias,
    ), patch(
        "app.routers.admin.criteria.CriteriaRepository",
        return_value=fake_repo,
    ), patch(
        "app.routers.admin.criteria.AppStateRepository",
        return_value=fake_state,
    ), patch(
        "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
        return_value="samehash",
    ):
        result = await reconcile_criteria(db=db2, _admin=object())

    # alias_map 변경이 없으므로 replace 는 호출되지 않음
    fake_alias.replace.assert_not_called()
    # DB 는 upsert rebuild → active 상태로 upsert
    fake_repo.delete_by_stable_ids_except.assert_awaited_once()
    assert len(upserted) == 1
    assert upserted[0]["stable_id"] == stable_id
    assert upserted[0]["status"] == "active"
    # sync_state 가 needs_resync → ok 로 복구
    assert result["sync_state"] == "ok"
    assert result["ok"] is True
    assert state_values[KEY_SYNC_STATE] == "ok"
    assert state_values[KEY_LAST_SYNCED_AT] is not None


@pytest.mark.asyncio
async def test_activate_500_then_reconcile_does_not_apply_when_cloud_unchanged():
    """H2 — 사용자 양상 "재동기화해도 적용 안 됨" 분기.

    replace() 가 cloud 에 도달하지 못하고 실패한 경우 (예: upload 자체 5xx).
    재동기화 시 fetch 는 옛 alias_map (uploaded) 을 반환 → DB rebuild 는
    uploaded 상태로 insert → 사용자의 활성화 의도는 적용되지 않음. sync_state
    는 ok 로 복구되어 재동기화 버튼은 사라진다.

    이 대조군이 "있음" 표현의 반대 분기를 명확히 한다.
    """
    stable_id = "01HACTIVE"
    document_id = "fileSearchStores/s/documents/doc-active"

    # ---------- Phase 1: activate fails ----------
    db1 = AsyncMock()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    stable_id: AliasMapEntry(
                        alias=None, status="uploaded", activated_at=None,
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock(
            side_effect=RuntimeError("upload_to_file_search_store 503"),
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db1,
            )

        assert exc_info.value.status_code == 500
        state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")

    # ---------- Phase 2: reconcile finds cloud still on "uploaded" ----------
    db2 = MagicMock()
    db2.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db2.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    fake_client = MagicMock()
    fake_vec = MagicMock()
    fake_vec.file_search_service.client = fake_client
    fake_vec.list_criteria_documents = AsyncMock(return_value=[
        _doc(document_id, stable_id),
    ])

    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(return_value=(
        "docs/alias-map",
        AliasMap(
            schema_version=1,
            updated_at="2026-05-15T00:00:00Z",
            entries={
                stable_id: AliasMapEntry(
                    alias=None, status="uploaded", activated_at=None,
                ),
            },
        ),
    ))
    fake_alias.replace = AsyncMock()

    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()
    fake_repo.delete_by_stable_ids_except = AsyncMock()
    upserted: list[dict] = []

    async def _upsert_from_cloud(**kwargs):
        upserted.append(kwargs)

    fake_repo.upsert_from_cloud = _upsert_from_cloud
    fake_repo.get_criteria_by_stable_id = AsyncMock(return_value=None)

    state_values: dict[str, object] = {
        "criteria_api_key_hash": "samehash",
        "criteria_sync_state": "needs_resync",
        "criteria_migration_v2_done": "true",
    }
    fake_state = MagicMock()
    fake_state.get = AsyncMock(side_effect=lambda key: state_values.get(key))
    fake_state.set = AsyncMock(side_effect=lambda k, v: state_values.__setitem__(k, v))

    async def _set_many(values):
        state_values.update(values)

    fake_state.set_many = AsyncMock(side_effect=_set_many)

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService",
        return_value=fake_vec,
    ), patch(
        "app.services.criteria_alias_map_service.CriteriaAliasMapService",
        return_value=fake_alias,
    ), patch(
        "app.routers.admin.criteria.CriteriaRepository",
        return_value=fake_repo,
    ), patch(
        "app.routers.admin.criteria.AppStateRepository",
        return_value=fake_state,
    ), patch(
        "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
        return_value="samehash",
    ):
        result = await reconcile_criteria(db=db2, _admin=object())

    fake_alias.replace.assert_not_called()
    fake_repo.delete_by_stable_ids_except.assert_awaited_once()
    assert len(upserted) == 1
    # DB 는 cloud truth 를 따라 uploaded 로 rebuild — 활성화 의도 적용 안 됨
    assert upserted[0]["status"] == "uploaded"
    # 그러나 sync_state 는 ok 로 복구 → 재동기화 버튼은 사라진다
    assert result["sync_state"] == "ok"
    assert result["ok"] is True
