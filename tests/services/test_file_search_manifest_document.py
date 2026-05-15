import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.file_search_service import FileSearchService


def _service_with_client(client):
    service = FileSearchService.__new__(FileSearchService)
    service.client = client
    return service


@pytest.mark.asyncio
async def test_download_document_bytes_reads_manifest_payload_from_metadata():
    payload = b'{"schema_version":1,"criteria":[]}'
    encoded = base64.b64encode(payload).decode("ascii")
    doc = SimpleNamespace(
        custom_metadata=[
            SimpleNamespace(
                key="manifest_payload_base64",
                string_list_value=SimpleNamespace(
                    values=[encoded[:10], encoded[10:]]
                ),
                string_value=None,
            )
        ]
    )

    client = MagicMock()
    client.file_search_stores.documents.get.return_value = doc
    service = _service_with_client(client)

    result = await service.download_document_bytes("store-id", "doc-name")
    assert result == payload
    client.files.download.assert_not_called()


@pytest.mark.asyncio
async def test_download_document_bytes_skips_files_api_for_store_document():
    client = MagicMock()
    client.file_search_stores.documents.get.return_value = SimpleNamespace(
        custom_metadata=[]
    )
    client.files.download.side_effect = AssertionError("wrong API")
    service = _service_with_client(client)

    with pytest.raises(RuntimeError, match="not downloadable"):
        await service.download_document_bytes("store-id", "doc-name")

    client.files.download.assert_not_called()


@pytest.mark.asyncio
async def test_replace_single_document_uses_safe_tempfile_metadata():
    client = MagicMock()
    client.file_search_stores.documents.list.return_value = []

    operation = MagicMock()
    operation.done = True
    operation.response.document_name = (
        "fileSearchStores/store/documents/manifest"
    )
    client.file_search_stores.upload_to_file_search_store.return_value = (
        operation
    )

    service = _service_with_client(client)

    with patch(
        "app.services.file_search_service.tempfile.mktemp",
        side_effect=AssertionError("mktemp must not be used"),
    ):
        document_id = await service.replace_single_document(
            store_id="fileSearchStores/store",
            display_name="rubric-manifest.json",
            content=b'{"schema_version":1,"criteria":[]}',
            mime_type="application/json",
        )

    assert document_id == "fileSearchStores/store/documents/manifest"
    call_args = client.file_search_stores.upload_to_file_search_store.call_args
    config = call_args.kwargs["config"]
    assert config["mime_type"] == "application/json"
    assert config["custom_metadata"][0]["key"] == "manifest_payload_base64"
