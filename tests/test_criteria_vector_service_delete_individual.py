"""delete_criteria가 documents.delete(name=...)를 호출 (store 재생성 X)"""
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_delete_criteria_calls_documents_delete_by_name():
    from app.services.criteria_vector_service import CriteriaVectorService

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = MagicMock()
    delete_mock = MagicMock()
    svc.file_search_service.client.file_search_stores.documents.delete = delete_mock

    ok = await svc.delete_criteria(document_id="fileSearchStores/x/documents/foo")

    assert ok is True
    delete_mock.assert_called_once_with(name="fileSearchStores/x/documents/foo")


@pytest.mark.asyncio
async def test_delete_criteria_does_not_recreate_store():
    from app.services.criteria_vector_service import CriteriaVectorService

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = MagicMock()

    await svc.delete_criteria(document_id="fileSearchStores/x/documents/foo")

    svc.file_search_service.client.file_search_stores.create.assert_not_called()
    svc.file_search_service.client.file_search_stores.delete.assert_not_called()
