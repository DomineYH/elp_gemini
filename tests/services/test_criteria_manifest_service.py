# tests/services/test_criteria_manifest_service.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.criteria_manifest import Manifest, ManifestEntry
from app.services.criteria_manifest_service import (
    CloudUnavailable,
    CriteriaManifestService,
)


@pytest.mark.asyncio
async def test_fetch_returns_empty_manifest_when_store_missing():
    fake_fs = AsyncMock()
    fake_fs.get_or_create_store = AsyncMock(return_value=("store-id", True))
    fake_fs.list_documents = AsyncMock(return_value=[])
    svc = CriteriaManifestService(file_search_service=fake_fs)
    m = await svc.fetch()
    assert isinstance(m, Manifest)
    assert m.criteria == []


@pytest.mark.asyncio
async def test_publish_from_db_uploads_manifest():
    fake_fs = AsyncMock()
    fake_fs.get_or_create_store = AsyncMock(return_value=("store-id", False))
    fake_fs.replace_single_document = AsyncMock(return_value="doc-id")

    fake_repo = AsyncMock()
    fake_repo.get_all_criteria = AsyncMock(
        return_value=[
            MagicMock(
                document_id="files/x",
                title="r.pdf",
                display_alias=None,
                status="active",
                created_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
                activated_at=None,
            )
        ]
    )

    svc = CriteriaManifestService(file_search_service=fake_fs)
    await svc.publish_from_db(fake_repo)
    fake_fs.replace_single_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_raises_cloud_unavailable_on_client_error():
    fake_fs = AsyncMock()
    fake_fs.get_or_create_store = AsyncMock(
        side_effect=RuntimeError("network down")
    )
    svc = CriteriaManifestService(file_search_service=fake_fs)
    with pytest.raises(CloudUnavailable):
        await svc.fetch()


@pytest.mark.asyncio
async def test_fetch_parses_existing_manifest():
    valid_manifest_json = (
        '{"schema_version":1,'
        '"generated_at":"2026-05-15T00:00:00Z",'
        '"criteria":[{"document_id":"files/x","title":"r.pdf",'
        '"display_alias":null,"status":"active",'
        '"created_at":null,"activated_at":null}]}'
    )
    fake_doc = MagicMock(display_name="rubric-manifest.json", id="doc1")
    fake_fs = AsyncMock()
    fake_fs.get_or_create_store = AsyncMock(return_value=("store-id", False))
    fake_fs.list_documents = AsyncMock(return_value=[fake_doc])
    fake_fs.download_document_bytes = AsyncMock(
        return_value=valid_manifest_json.encode("utf-8")
    )
    svc = CriteriaManifestService(file_search_service=fake_fs)
    m = await svc.fetch()
    assert len(m.criteria) == 1
    assert m.criteria[0].document_id == "files/x"
