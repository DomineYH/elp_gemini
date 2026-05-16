"""alias-map replace — upload new succeeds before delete old"""
from unittest.mock import MagicMock

import pytest
from google.genai import errors as genai_errors

from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_alias_map_service import CriteriaAliasMapService


def _store():
    s = MagicMock()
    s.name = "stores/x"
    s.display_name = "rubric-store"
    return s


def _enforcing_upload(document_name):
    """Mimic Google File Search's 256-char string_list_value limit (issue #60)."""
    def fake_upload(**kwargs):
        config = kwargs.get("config") or {}
        for entry in config.get("custom_metadata") or []:
            sl = entry.get("string_list_value") or {}
            for value in sl.get("values") or []:
                if len(value) > 256:
                    raise genai_errors.ClientError(
                        400,
                        {"error": {
                            "code": 400,
                            "status": "INVALID_ARGUMENT",
                            "message": (
                                "* UploadToFileSearchStoreRequest."
                                "custom_metadata[1].string_list_value."
                                "values[0]: StringList value cannot be "
                                "more than 256 characters long.\n"
                            ),
                        }},
                        MagicMock(),
                    )
        op = MagicMock(done=True)
        op.response.document_name = document_name
        return op

    return fake_upload


@pytest.mark.asyncio
async def test_replace_uploads_then_deletes_old():
    """기존 doc.name이 있을 때: upload 성공 후에야 delete 호출"""
    client = MagicMock()
    client.file_search_stores.list.return_value = iter([_store()])

    client.file_search_stores.upload_to_file_search_store.side_effect = (
        _enforcing_upload("docs/alias-map-new")
    )
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
    client.file_search_stores.upload_to_file_search_store.side_effect = (
        _enforcing_upload("docs/alias-map-1")
    )
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
