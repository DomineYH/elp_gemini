"""upload_criteria가 stable_id와 original_title_b64 메타데이터를 포함"""
import base64
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_upload_criteria_preserves_raw_list_metadata_in_sdk_call():
    from app.services.criteria_vector_service import CriteriaVectorService

    client = MagicMock()
    store = MagicMock()
    store.name = "stores/rubric"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = [store]

    op = MagicMock()
    op.done = True
    op.response.document_name = "docs/abc"
    op.response.parent = "stores/rubric"
    client.file_search_stores.upload_to_file_search_store.return_value = op

    with patch(
        "app.services.file_search_service.FileSearchService.get_client",
        return_value=client,
    ):
        svc = CriteriaVectorService()
        result = await svc.upload_criteria(
            file_path="/tmp/x.pdf",
            title="한글 평가기준.pdf",
            stable_id="01HABC",
        )

    assert result["document_id"] == "docs/abc"

    upload_call = client.file_search_stores.upload_to_file_search_store.call_args
    custom_metadata = upload_call.kwargs["config"]["custom_metadata"]
    meta = {entry["key"]: entry for entry in custom_metadata}

    assert meta["type"] == {"key": "type", "string_value": "criteria"}
    assert meta["stable_id"] == {
        "key": "stable_id",
        "string_value": "01HABC",
    }

    expected_b64 = base64.b64encode("한글 평가기준.pdf".encode()).decode()
    assert meta["original_title_b64"] == {
        "key": "original_title_b64",
        "string_list_value": {"values": [expected_b64]},
    }

    created_at_values = meta["created_at"]["string_list_value"]["values"]
    assert len(created_at_values) == 1
    assert ":" in created_at_values[0]
    assert "_" not in created_at_values[0]
    assert created_at_values[0].endswith("Z")
