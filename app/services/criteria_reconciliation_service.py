"""평가기준 클라우드 reconcile 서비스.

API key 변경을 sha256 해시로 감지하고, 매니페스트 store의 내용을 기준으로
로컬 SQLite + 업로드 캐시를 재구성한다. 동시 호출은 module-level lock으로 직렬화.
"""
import asyncio
import hashlib
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_API_KEY_HASH,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    SYNC_STATE_ERROR,
    SYNC_STATE_NEEDS_RESYNC,
    SYNC_STATE_OK,
)
from app.repositories.criteria_repository import CriteriaRepository
from app.schemas.criteria_manifest import (
    MANIFEST_SCHEMA_VERSION,
    Manifest,
    ManifestEntry,
)
from app.services.criteria_manifest_service import (
    CloudUnavailable,
    CriteriaManifestService,
)
from app.services.criteria_vector_service import CriteriaVectorService

logger = logging.getLogger(__name__)

_reconcile_lock = asyncio.Lock()


@dataclass
class ReconcileResult:
    ok: bool = False
    skipped: bool = False
    count: int = 0
    error: Optional[str] = None


class CriteriaReconciliationService:
    def __init__(
        self,
        app_state_repo: AppStateRepository,
        manifest_service: CriteriaManifestService,
        criteria_repo: CriteriaRepository,
        vector_service: CriteriaVectorService,
        current_api_key: Optional[str] = None,
    ):
        self.app_state = app_state_repo
        self.manifest_svc = manifest_service
        self.criteria_repo = criteria_repo
        self.vector_svc = vector_service
        self._api_key = current_api_key or settings.GOOGLE_API_KEY

    @staticmethod
    def _hash_key(api_key: Optional[str]) -> Optional[str]:
        if not api_key:
            return None
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def _wipe_upload_dir(self) -> None:
        target = Path(settings.CRITERIA_UPLOAD_DIR).resolve(strict=False)
        # symlink 거부 (디렉토리 자체가 symlink면 거부)
        if Path(settings.CRITERIA_UPLOAD_DIR).is_symlink():
            raise RuntimeError(
                f"refusing to wipe symlinked upload dir: {target}"
            )
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    async def reconcile(self) -> ReconcileResult:
        async with _reconcile_lock:
            current_hash = self._hash_key(self._api_key)
            stored_hash = await self.app_state.get(KEY_API_KEY_HASH)
            stored_state = await self.app_state.get(KEY_SYNC_STATE)
            key_changed = stored_hash != current_hash

            if not key_changed and stored_state == SYNC_STATE_OK:
                return ReconcileResult(skipped=True)

            try:
                manifest = await self.manifest_svc.fetch()
                cloud_doc_ids = await self.vector_svc.list_document_ids()
            except CloudUnavailable as e:
                error_msg = str(e)
                if key_changed:
                    try:
                        self._wipe_upload_dir()
                    except Exception as wipe_err:
                        logger.error("wipe failed: %s", wipe_err)
                        error_msg = f"{error_msg} (wipe also failed: {wipe_err})"
                    await self.criteria_repo.truncate()
                    await self.app_state.set_many(
                        {
                            KEY_API_KEY_HASH: current_hash,
                            KEY_SYNC_STATE: SYNC_STATE_ERROR,
                            KEY_SYNC_ERROR: error_msg,
                        }
                    )
                else:
                    await self.app_state.set(KEY_SYNC_STATE, SYNC_STATE_NEEDS_RESYNC)
                    await self.app_state.set(KEY_SYNC_ERROR, str(e))
                return ReconcileResult(ok=False, error=str(e))

            manifest_ids = {e.document_id for e in manifest.criteria}
            cloud_ids = set(cloud_doc_ids)
            orphans_in_manifest = manifest_ids - cloud_ids
            orphans_in_cloud = cloud_ids - manifest_ids

            entries: list[ManifestEntry] = [
                e for e in manifest.criteria if e.document_id not in orphans_in_manifest
            ]
            for orphan_id in orphans_in_cloud:
                entries.append(
                    ManifestEntry(
                        document_id=orphan_id,
                        title=orphan_id,
                        display_alias=None,
                        status="uploaded",
                    )
                )

            await self.criteria_repo.truncate()
            await self.criteria_repo.bulk_insert(
                [
                    {
                        "title": e.title,
                        "document_id": e.document_id,
                        "display_alias": e.display_alias,
                        "status": e.status,
                        "created_at": e.created_at,
                        "activated_at": e.activated_at,
                        "file_size": 0,
                        "file_path": e.document_id,
                        "uploaded_by": "<cloud-sync>",
                    }
                    for e in entries
                ]
            )
            try:
                self._wipe_upload_dir()
            except Exception as e:
                logger.error("upload dir wipe failed: %s", e)

            if orphans_in_cloud:
                repaired = Manifest(
                    schema_version=MANIFEST_SCHEMA_VERSION,
                    generated_at=datetime.now(tz=timezone.utc),
                    criteria=entries,
                )
                try:
                    await self.manifest_svc.upload(repaired)
                except CloudUnavailable as e:
                    logger.warning("self-heal manifest upload failed: %s", e)
                    await self.app_state.set_many(
                        {
                            KEY_API_KEY_HASH: current_hash,
                            KEY_LAST_SYNCED_AT: datetime.now(tz=timezone.utc).isoformat(),
                            KEY_SYNC_STATE: SYNC_STATE_NEEDS_RESYNC,
                            KEY_SYNC_ERROR: f"self-heal upload failed: {e}",
                        }
                    )
                    return ReconcileResult(ok=False, count=len(entries), error=str(e))

            await self.app_state.set_many(
                {
                    KEY_API_KEY_HASH: current_hash,
                    KEY_LAST_SYNCED_AT: datetime.now(tz=timezone.utc).isoformat(),
                    KEY_SYNC_STATE: SYNC_STATE_OK,
                    KEY_SYNC_ERROR: None,
                }
            )
            return ReconcileResult(ok=True, count=len(entries))
