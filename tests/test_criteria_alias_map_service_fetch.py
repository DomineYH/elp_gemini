"""alias-map 문서 fetch & parse — type=alias_map 만 인식"""
import pytest
from unittest.mock import MagicMock

from app.services.alias_map_codec import encode_alias_map_payload, ALIAS_MAP_PAYLOAD_KEY
from app.services.criteria_alias_map_service import (
    CriteriaAliasMapService,
    _read_metadata_kv,
)


def _meta(key, *, string_value=None, string_list_value=None):
    m = MagicMock()
    m.key = key
    m.string_value = string_value
    m.string_list_value = MagicMock(values=string_list_value) if string_list_value is not None else None
    return m


def _doc(name, metas):
    d = MagicMock()
    d.name = name
    d.custom_metadata = metas
    return d


def test_read_metadata_kv_accepts_dict_string_list_value():
    kv = _read_metadata_kv([
        {
            "key": "payload",
            "string_value": "a",
            "string_list_value": {"values": ["a", "b"]},
        }
    ])

    assert kv["payload"] == ("a", ["a", "b"])


@pytest.mark.asyncio
async def test_fetch_returns_none_when_no_alias_map_doc():
    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/a", [_meta("type", string_value="criteria")]),
    ])

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    result = await svc.fetch()
    assert result is None


@pytest.mark.asyncio
async def test_fetch_parses_payload_chunks():
    payload = {"schema_version": 1, "updated_at": "2026-05-15T00:00:00Z",
               "entries": {"01HID": {"alias": "한글", "status": "active", "activated_at": None}}}
    chunks = encode_alias_map_payload(payload)

    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/alias-map", [
            _meta("type", string_value="alias_map"),
            _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=chunks),
        ]),
    ])

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    fetched = await svc.fetch()
    assert fetched is not None
    doc_name, alias_map = fetched
    assert doc_name == "docs/alias-map"
    assert alias_map.entries["01HID"].alias == "한글"
