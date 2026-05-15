import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.config import settings
from app.schemas.criteria_manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    Manifest,
    ManifestEntry,
)
from app.services.file_search_service import FileSearchService

if TYPE_CHECKING:
    from app.repositories.criteria_repository import CriteriaRepository

logger = logging.getLogger(__name__)


class CloudUnavailable(RuntimeError):
    """Gemini File Search 동작 불가(네트워크/권한/5xx)."""


class CriteriaManifestService:
    """rubric-metadata-store 의 매니페스트 build/fetch/publish."""

    def __init__(self, file_search_service: FileSearchService | None = None):
        self.file_search_service = file_search_service or FileSearchService()
        self.store_name = settings.FS_RUBRIC_METADATA_STORE_NAME

    async def fetch(self) -> Manifest:
        try:
            store_id, _ = await self.file_search_service.get_or_create_store(
                self.store_name
            )
            docs = await self.file_search_service.list_documents(store_id)
        except Exception as exc:
            logger.warning("매니페스트 fetch 실패: %s", exc)
            raise CloudUnavailable(str(exc)) from exc

        manifest_doc = next(
            (d for d in docs if getattr(d, "display_name", "") == MANIFEST_FILENAME),
            None,
        )
        if manifest_doc is None:
            logger.info("매니페스트 문서가 없어 빈 매니페스트 반환")
            return Manifest(
                schema_version=MANIFEST_SCHEMA_VERSION,
                generated_at=datetime.now(tz=timezone.utc),
                criteria=[],
            )

        document_name = getattr(manifest_doc, "name", None) or getattr(
            manifest_doc, "id", None
        )
        if not document_name:
            raise CloudUnavailable("매니페스트 문서 이름을 확인할 수 없습니다")

        try:
            raw_bytes = await self.file_search_service.download_document_bytes(
                store_id, document_name
            )
            return Manifest.model_validate_json(raw_bytes)
        except Exception as exc:
            logger.warning("매니페스트 다운로드 실패: %s", exc)
            raise CloudUnavailable(str(exc)) from exc

    async def upload(self, manifest: Manifest) -> None:
        payload = manifest.model_dump_json(by_alias=True).encode("utf-8")
        try:
            store_id, _ = await self.file_search_service.get_or_create_store(
                self.store_name
            )
            await self.file_search_service.replace_single_document(
                store_id=store_id,
                display_name=MANIFEST_FILENAME,
                content=payload,
                mime_type="application/json",
            )
        except Exception as exc:
            logger.error("매니페스트 upload 실패: %s", exc)
            raise CloudUnavailable(str(exc)) from exc
        logger.info(
            "매니페스트 업로드 완료 (criteria=%d)", len(manifest.criteria)
        )

    async def publish_from_db(
        self, criteria_repo: "CriteriaRepository"
    ) -> Manifest:
        rows = await criteria_repo.get_all_criteria()
        manifest = Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            generated_at=datetime.now(tz=timezone.utc),
            criteria=[
                ManifestEntry(
                    document_id=r.document_id,
                    title=r.title,
                    display_alias=r.display_alias,
                    status=r.status,
                    created_at=r.created_at,
                    activated_at=r.activated_at,
                )
                for r in rows
                if r.document_id is not None
            ],
        )
        await self.upload(manifest)
        return manifest
