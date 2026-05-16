"""
Criteria 클라우드 동기화 (v2 — alias_map 기반)

설계: docs/superpowers/specs/2026-05-15-criteria-cloud-metadata-design.md §6
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_API_KEY_HASH,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
)
from app.repositories.criteria_repository import CriteriaRepository
from app.schemas.alias_map import AliasMap, AliasMapEntry, empty_alias_map
from app.services.criteria_alias_map_service import CriteriaAliasMapService
from app.services.criteria_vector_service import CriteriaVectorService

logger = logging.getLogger(__name__)

_reconcile_lock = asyncio.Lock()


def sha256_hex_of_api_key() -> str:
    key = (settings.GOOGLE_API_KEY or "").encode("utf-8")
    return hashlib.sha256(key).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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

    async def reconcile(self) -> ReconcileResult:
        async with _reconcile_lock:
            current_hash = sha256_hex_of_api_key()
            async with self._db.begin():
                stored_hash = await self._state.get(KEY_API_KEY_HASH)
                stored_state = await self._state.get(KEY_SYNC_STATE)
                migration_v2_done = await self._state.get(
                    "criteria_migration_v2_done"
                )
            key_changed = stored_hash != current_hash

            if (
                not key_changed
                and stored_state == "ok"
                and migration_v2_done == "true"
            ):
                return ReconcileResult(skipped=True)

            try:
                # Legacy migration (Task 13 will add migrate_from_legacy_manifest).
                # Lazy import so the absence of the module does not block reconcile.
                try:
                    from app.services.criteria_legacy_migration import (  # noqa: F401
                        migrate_from_legacy_manifest,
                    )
                    async with self._db.begin():
                        await migrate_from_legacy_manifest(
                            client=self._vec.file_search_service.client,
                            app_state=self._state,
                        )
                except ImportError:
                    pass  # Task 13 will add this module
                except Exception as e:
                    logger.warning(f"legacy migration 실패 (계속 진행): {e}")

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
                        stable_ids_by_document[document_id] = document_id
                        logger.warning(
                            "Document %s migrated without proper stable_id; "
                            "will use surrogate",
                            document_id,
                        )

                fetched = await self._alias.fetch()
                old_doc_name, alias_map = (
                    fetched if fetched else (None, empty_alias_map(_now_iso()))
                )

                valid_stable_ids = set(stable_ids_by_document.values())

                # 4a. Remove entries pointing to nonexistent docs
                cleaned = {
                    sid: e
                    for sid, e in alias_map.entries.items()
                    if sid in valid_stable_ids
                }
                # 4b. Synthesize entries for unmapped cloud docs
                for d in criteria_docs:
                    sid = stable_ids_by_document[d["document_id"]]
                    if sid not in cleaned:
                        cleaned[sid] = AliasMapEntry(
                            alias=None, status="uploaded", activated_at=None
                        )

                # Single re-upload if anything changed
                if cleaned != alias_map.entries:
                    alias_map = AliasMap(
                        schema_version=1,
                        updated_at=_now_iso(),
                        entries=cleaned,
                    )
                    await self._alias.replace(
                        alias_map, old_doc_name=old_doc_name
                    )

                # Rebuild local DB cache
                async with self._db.begin():
                    await self._repo.truncate()
                    for d in criteria_docs:
                        sid = stable_ids_by_document[d["document_id"]]
                        entry = cleaned[sid]
                        title_b64 = _kv_string(d, "original_title_b64") or ""
                        try:
                            title = (
                                base64.b64decode(title_b64).decode("utf-8")
                                if title_b64
                                else d.get("display_name") or sid
                            )
                        except Exception:
                            title = d.get("display_name") or sid
                        await self._repo.insert(
                            stable_id=sid,
                            document_id=d["document_id"],
                            title=title,
                            display_alias=entry.alias,
                            status=entry.status,
                            created_at=_kv_string(d, "created_at"),
                            activated_at=entry.activated_at,
                        )

                    await self._state.set_many({
                        KEY_API_KEY_HASH: current_hash,
                        KEY_LAST_SYNCED_AT: _now_iso(),
                        KEY_SYNC_STATE: "ok",
                        KEY_SYNC_ERROR: None,
                    })
                return ReconcileResult(ok=True, count=len(criteria_docs))

            except Exception as e:
                logger.error(f"reconcile 실패: {e}", exc_info=True)
                async with self._db.begin():
                    await self._state.set_many({
                        KEY_SYNC_STATE: (
                            "error" if key_changed else "needs_resync"
                        ),
                        KEY_SYNC_ERROR: str(e),
                    })
                return ReconcileResult(error=str(e))


def _kv_string(doc: dict, key: str) -> Optional[str]:
    sv, values = doc.get("custom_metadata_kv", {}).get(key, (None, []))
    if sv is not None:
        return sv
    if values:
        return "".join(values)
    return None
