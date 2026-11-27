"""
Criteria 클라우드 동기화 (v2 — alias_map 기반)

설계: docs/superpowers/specs/2026-05-15-criteria-cloud-metadata-design.md §6
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.repositories.app_state_repository import (
    KEY_API_KEY_HASH,
    KEY_LAST_ALIAS_MAP_UPDATED_AT,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    AppStateRepository,
)
from app.repositories.criteria_repository import CriteriaRepository
from app.schemas.alias_map import AliasMap, AliasMapEntry, empty_alias_map
from app.services.criteria_alias_map_service import (
    AliasMapParseError,
    CriteriaAliasMapService,
    alias_map_mutation_lock,
)
from app.services.criteria_vector_service import CriteriaVectorService
from app.utils.gemini_retry import safe_error_text, safe_exc_info

logger = logging.getLogger(__name__)

_reconcile_lock = asyncio.Lock()
LEGACY_SURROGATE_PREFIX = "legacy_"


def sha256_hex_of_api_key() -> str:
    key = (settings.GOOGLE_API_KEY or "").encode("utf-8")
    return hashlib.sha256(key).hexdigest()


def legacy_surrogate_stable_id(document_id: str) -> str:
    """URL-safe surrogate for pre-v2 documents missing stable_id metadata."""
    digest = hashlib.sha1(document_id.encode("utf-8")).hexdigest()[:16]
    return f"{LEGACY_SURROGATE_PREFIX}{digest}"


def is_legacy_surrogate_stable_id(stable_id: str) -> bool:
    """Legacy surrogates cannot match cloud stable_id metadata filters."""
    return stable_id.startswith(LEGACY_SURROGATE_PREFIX)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_z(value: Optional[datetime]) -> Optional[str]:
    """DB의 시각(시간대 없으면 UTC) → alias_map의 'Z' 표기."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_active_entries(
    entries: dict[str, AliasMapEntry],
) -> dict[str, AliasMapEntry]:
    """Demote legacy surrogate active entries; allow multiple real actives."""
    normalized: dict[str, AliasMapEntry] = {}
    for sid, entry in entries.items():
        if entry.status == "active" and is_legacy_surrogate_stable_id(sid):
            normalized[sid] = entry.model_copy(
                update={
                    "status": "uploaded",
                    "activated_at": None,
                }
            )
        else:
            normalized[sid] = entry
    return normalized


@asynccontextmanager
async def _transaction_if_needed(db):
    in_transaction = getattr(db, "in_transaction", None)
    if callable(in_transaction) and in_transaction() is True:
        yield
        return

    async with db.begin():
        yield


@dataclass
class ReconcileResult:
    ok: bool = False
    skipped: bool = False
    error: Optional[str] = None
    count: int = 0


class CriteriaReconciliationService:
    def __init__(
        self,
        db,
        vector_service: CriteriaVectorService,
        alias_map_service: CriteriaAliasMapService,
        criteria_repo: CriteriaRepository,
        app_state_repo: AppStateRepository,
    ):
        self._db = db
        self._vec = vector_service
        self._alias = alias_map_service
        self._repo = criteria_repo
        self._state = app_state_repo

    async def reconcile(
        self,
        *,
        swallow_errors: bool = False,
        rebuild_alias_map_from_cache: bool = False,
    ) -> ReconcileResult:
        async with alias_map_mutation_lock:
            async with _reconcile_lock:
                current_hash = sha256_hex_of_api_key()
                async with _transaction_if_needed(self._db):
                    stored_hash = await self._state.get(KEY_API_KEY_HASH)
                    stored_state = await self._state.get(KEY_SYNC_STATE)
                    migration_v2_done = await self._state.get(
                        "criteria_migration_v2_done"
                    )
                    stored_alias_updated_at = await self._state.get(
                        KEY_LAST_ALIAS_MAP_UPDATED_AT
                    )
                key_changed = stored_hash != current_hash

                fetched_for_guard = None
                if (
                    not key_changed
                    and stored_state == "ok"
                    and migration_v2_done == "true"
                    and stored_alias_updated_at is not None
                ):
                    try:
                        fetched_for_guard = await self._alias.fetch()
                    except Exception:
                        # cloud 일시 장애 시에는 skip하지 않고
                        # 기존 로직으로 진행
                        fetched_for_guard = None
                    if (
                        fetched_for_guard is not None
                        and fetched_for_guard[1].updated_at
                        == stored_alias_updated_at
                    ):
                        return ReconcileResult(skipped=True)

                try:
                    # Task 13 will add migrate_from_legacy_manifest.
                    # Lazy import keeps its absence from blocking reconcile.
                    try:
                        from app.services.criteria_legacy_migration import (  # noqa: F401
                            migrate_from_legacy_manifest,
                        )

                        async with _transaction_if_needed(self._db):
                            await migrate_from_legacy_manifest(
                                client=self._vec.file_search_service.client,
                                app_state=self._state,
                            )
                    except ImportError:
                        pass  # Task 13 will add this module
                    except Exception as e:
                        logger.warning(
                            "legacy migration 실패 (계속 진행): %s", e
                        )

                    docs = await self._vec.list_criteria_documents()
                    criteria_docs = [
                        d for d in docs if _kv_string(d, "type") == "criteria"
                    ]
                    stable_ids_by_document: dict[str, str] = {}
                    for d in criteria_docs:
                        document_id = d["document_id"]
                        sid = _kv_string(d, "stable_id")
                        if sid:
                            stable_ids_by_document[document_id] = sid
                        else:
                            surrogate = legacy_surrogate_stable_id(document_id)
                            stable_ids_by_document[document_id] = surrogate
                            logger.warning(
                                "Document %s migrated without "
                                "proper stable_id; will use "
                                "legacy surrogate %s. This criterion "
                                "cannot be activated for evaluation; "
                                "delete and re-upload it to create v2 "
                                "metadata.",
                                document_id,
                                surrogate,
                            )

                    # 못 읽는 alias_map 문서들. None이 아니면 캐시로 다시 쓴다 (#471)
                    unreadable_docs: Optional[list[str]] = None
                    try:
                        fetched = (
                            fetched_for_guard
                            if fetched_for_guard is not None
                            else await self._alias.fetch()
                        )
                    except AliasMapParseError as e:
                        if not rebuild_alias_map_from_cache:
                            raise
                        unreadable_docs = e.doc_names
                        fetched = None

                    if rebuild_alias_map_from_cache and unreadable_docs is None:
                        # 읽히거나 없는 지도는 복구가 쓰지 않는다. 재동기화 버튼의 몫 (#471)
                        return ReconcileResult(skipped=True)

                    if unreadable_docs is not None:
                        async with _transaction_if_needed(self._db):
                            cached_entries = {
                                row.stable_id: AliasMapEntry(
                                    alias=row.display_alias,
                                    status=row.status,
                                    activated_at=(
                                        _iso_z(row.activated_at)
                                        if row.status == "active"
                                        else None
                                    ),
                                )
                                for row in await self._repo.get_all_criteria()
                                if row.stable_id
                            }
                        old_doc_name, alias_map = None, AliasMap(
                            schema_version=1,
                            updated_at=_now_iso(),
                            entries=cached_entries,
                        )
                    else:
                        old_doc_name, alias_map = (
                            fetched
                            if fetched
                            else (None, empty_alias_map(_now_iso()))
                        )

                    valid_stable_ids = set(stable_ids_by_document.values())

                    # 4a. Remove entries pointing to nonexistent docs
                    cleaned = {
                        sid: e
                        for sid, e in alias_map.entries.items()
                        if sid in valid_stable_ids
                    }
                    # 4b. Synthesize entries for unmapped cloud docs
                    #     (auto-active; 캐시 복구에서는 비활성 #471)
                    for d in criteria_docs:
                        sid = stable_ids_by_document[d["document_id"]]
                        if sid not in cleaned:
                            cleaned[sid] = (
                                AliasMapEntry(alias=None, status="uploaded")
                                if unreadable_docs is not None
                                else AliasMapEntry(
                                    alias=None,
                                    status="active",
                                    activated_at=_now_iso(),
                                )
                            )
                    cleaned = _normalize_active_entries(cleaned)

                    # Single re-upload if anything changed
                    if (
                        unreadable_docs is not None
                        or cleaned != alias_map.entries
                    ):
                        alias_map = AliasMap(
                            schema_version=1,
                            updated_at=_now_iso(),
                            entries=cleaned,
                        )
                        await self._alias.replace(
                            alias_map, old_doc_name=old_doc_name
                        )
                        if unreadable_docs is not None:
                            # 하나라도 남으면 새 문서가 있어도 계속 못 읽는다
                            await self._alias.delete_documents(unreadable_docs)

                    # Rebuild local DB cache (upsert preserves local-only cols)
                    async with _transaction_if_needed(self._db):
                        await self._repo.delete_by_stable_ids_except(
                            set(stable_ids_by_document.values())
                        )
                        for d in criteria_docs:
                            sid = stable_ids_by_document[d["document_id"]]
                            entry = cleaned[sid]
                            title_b64 = (
                                _kv_string(d, "original_title_b64") or ""
                            )
                            try:
                                title = (
                                    base64.b64decode(title_b64).decode("utf-8")
                                    if title_b64
                                    else d.get("display_name") or sid
                                )
                            except Exception:
                                title = d.get("display_name") or sid
                            await self._repo.upsert_from_cloud(
                                stable_id=sid,
                                document_id=d["document_id"],
                                title=title,
                                display_alias=entry.alias,
                                status=entry.status,
                                created_at=_kv_string(d, "created_at"),
                                activated_at=entry.activated_at,
                            )

                        await self._state.set_many(
                            {
                                KEY_API_KEY_HASH: current_hash,
                                KEY_LAST_SYNCED_AT: _now_iso(),
                                KEY_SYNC_STATE: "ok",
                                KEY_SYNC_ERROR: None,
                                KEY_LAST_ALIAS_MAP_UPDATED_AT: alias_map.updated_at,
                            }
                        )
                    return ReconcileResult(ok=True, count=len(criteria_docs))

                except Exception as e:
                    # 원문 대신 종류(와 코드)만 응답·저장값·로그에 쓴다 (#485)
                    error_text = safe_error_text(e)
                    logger.error(
                        "reconcile 실패: %s",
                        error_text,
                        exc_info=safe_exc_info(e),
                    )
                    # 파싱 실패는 일시 오류가 아니다: 자동 검사도 표시한다 (#471)
                    if (
                        swallow_errors
                        and not key_changed
                        and not isinstance(e, AliasMapParseError)
                    ):
                        return ReconcileResult(error=error_text)
                    async with _transaction_if_needed(self._db):
                        await self._state.set_many(
                            {
                                KEY_SYNC_STATE: (
                                    "error" if key_changed else "needs_resync"
                                ),
                                KEY_SYNC_ERROR: error_text,
                            }
                        )
                    return ReconcileResult(error=error_text)


def _kv_string(doc: dict, key: str) -> Optional[str]:
    sv, values = doc.get("custom_metadata_kv", {}).get(key, (None, []))
    if sv is not None:
        return sv
    if values:
        return "".join(values)
    return None
