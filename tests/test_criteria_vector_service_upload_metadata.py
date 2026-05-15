"""upload_criteria가 stable_id와 original_title_b64 메타데이터를 포함"""
import base64
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_upload_criteria_attaches_stable_and_b64_title():
    from app.services.criteria_vector_service import CriteriaVectorService

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = MagicMock()
    svc.file_search_service.upload_document = MagicMock()

    async def fake_upload(**kwargs):
        return {"document_id": "docs/abc", "store_id": "stores/x"}

    svc.file_search_service.upload_document.side_effect = fake_upload

    result = await svc.upload_criteria(
        file_path="/tmp/x.pdf",
        title="한글 평가기준.pdf",
        stable_id="01HABC",
    )
    assert result["document_id"] == "docs/abc"

    call = svc.file_search_service.upload_document.call_args
    meta = call.kwargs["metadata"]
    assert meta["type"] == "criteria"
    assert meta["stable_id"] == "01HABC"
    # base64-encoded UTF-8 of the original title
    expected_b64 = base64.b64encode("한글 평가기준.pdf".encode()).decode()
    assert meta["original_title_b64"] == expected_b64
    assert "created_at" in meta
