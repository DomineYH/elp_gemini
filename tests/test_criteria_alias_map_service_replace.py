"""alias-map replace — upload new succeeds before delete old"""
from unittest.mock import MagicMock

import pytest

from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_alias_map_service import CriteriaAliasMapService


def _store():
    s = MagicMock()
    s.name = "stores/x"
    s.display_name = "rubric-store"
    return s


@pytest.mark.asyncio
async def test_replace_uploads_then_deletes_old():
    """기존 doc.name이 있을 때: upload 성공 후에야 delete 호출"""
    client = MagicMock()
    client.file_search_stores.list.return_value = iter([_store()])

    upload_op = MagicMock(done=True)
    upload_op.response.document_name = "docs/alias-map-new"
    client.file_search_stores.upload_to_file_search_store.return_value = upload_op
    client.file_search_stores.documents.delete = MagicMock()

    am = AliasMap(schema_version=1, updated_at="2026-05-15T00:00:00Z",
                  entries={"01HID": AliasMapEntry(alias="x", status="uploaded", activated_at=None)})

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    new_name = await svc.replace(am, old_doc_name="docs/alias-map-old")

    assert new_name == "docs/alias-map-new"
    client.file_search_stores.upload_to_file_search_store.assert_called_once()
    client.file_search_stores.documents.delete.assert_called_once_with(name="docs/alias-map-old")


@pytest.mark.asyncio
async def test_replace_does_not_delete_when_no_old_doc():
    client = MagicMock()
    client.file_search_stores.list.return_value = iter([_store()])
    upload_op = MagicMock(done=True)
    upload_op.response.document_name = "docs/alias-map-1"
    client.file_search_stores.upload_to_file_search_store.return_value = upload_op
    client.file_search_stores.documents.delete = MagicMock()

    am = AliasMap(schema_version=1, updated_at="2026-05-15T00:00:00Z", entries={})

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    await svc.replace(am, old_doc_name=None)

    client.file_search_stores.documents.delete.assert_not_called()


@pytest.mark.asyncio
async def test_replace_does_not_delete_when_upload_fails():
    client = MagicMock()
    client.file_search_stores.list.return_value = iter([_store()])
    client.file_search_stores.upload_to_file_search_store.side_effect = RuntimeError("boom")
    client.file_search_stores.documents.delete = MagicMock()

    am = AliasMap(schema_version=1, updated_at="2026-05-15T00:00:00Z", entries={})

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    with pytest.raises(RuntimeError):
        await svc.replace(am, old_doc_name="docs/alias-map-old")

    client.file_search_stores.documents.delete.assert_not_called()
