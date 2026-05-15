"""list_criteria_documents가 custom_metadata를 함께 반환"""
from unittest.mock import MagicMock

import pytest


def _meta(key, string_value=None, string_list=None):
    m = MagicMock()
    m.key = key
    m.string_value = string_value
    m.string_list_value = MagicMock(values=string_list) if string_list else None
    return m


def _doc(name, metas, display_name="x"):
    d = MagicMock()
    d.name = name
    d.display_name = display_name
    d.custom_metadata = metas
    return d


@pytest.mark.asyncio
async def test_list_returns_documents_with_raw_metadata():
    from app.services.criteria_vector_service import CriteriaVectorService

    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"

    client = MagicMock()
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/a", [
            _meta("type", string_value="criteria"),
            _meta("stable_id", string_value="01HA"),
        ]),
        _doc("docs/b", [_meta("type", string_value="alias_map")]),
    ])

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = client
    svc.store_name = "rubric-store"

    docs = await svc.list_criteria_documents()
    assert len(docs) == 2
    by_name = {d["document_id"]: d for d in docs}
    assert by_name["docs/a"]["custom_metadata_kv"]["type"] == ("criteria", [])
    assert by_name["docs/a"]["custom_metadata_kv"]["stable_id"] == ("01HA", [])
    assert by_name["docs/b"]["custom_metadata_kv"]["type"] == ("alias_map", [])
