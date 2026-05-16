"""alias-map 문서 fetch & parse — type=alias_map 만 인식"""
import pytest
from unittest.mock import MagicMock

from app.services.alias_map_codec import encode_alias_map_payload, ALIAS_MAP_PAYLOAD_KEY
from app.services.criteria_alias_map_service import (
    AliasMapParseError,
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


def _alias_map_chunks(updated_at, alias):
    return encode_alias_map_payload({
        "schema_version": 1,
        "updated_at": updated_at,
        "entries": {
            "01HID": {
                "alias": alias,
                "status": "uploaded",
                "activated_at": None,
            },
        },
    })


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


@pytest.mark.asyncio
async def test_fetch_returns_newest_alias_map_when_duplicates_exist(caplog):
    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.delete = MagicMock()
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/alias-map-old", [
            _meta("type", string_value="alias_map"),
            _meta(
                ALIAS_MAP_PAYLOAD_KEY,
                string_list_value=_alias_map_chunks(
                    "2026-05-15T00:00:00Z", "old"
                ),
            ),
        ]),
        _doc("docs/alias-map-new", [
            _meta("type", string_value="alias_map"),
            _meta(
                ALIAS_MAP_PAYLOAD_KEY,
                string_list_value=_alias_map_chunks(
                    "2026-05-15T00:01:00Z", "new"
                ),
            ),
        ]),
    ])

    caplog.set_level("WARNING", logger="app.services.criteria_alias_map_service")
    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")

    fetched = await svc.fetch()

    assert fetched is not None
    doc_name, alias_map = fetched
    assert doc_name == "docs/alias-map-new"
    assert alias_map.entries["01HID"].alias == "new"
    assert "multiple alias_map documents" in caplog.text
    client.file_search_stores.documents.delete.assert_called_once_with(
        name="docs/alias-map-old"
    )


@pytest.mark.asyncio
async def test_fetch_raises_when_newest_alias_map_is_unparseable(caplog):
    old_chunks = _alias_map_chunks("2026-05-15T00:00:00Z", "old")
    newer_invalid_chunks = encode_alias_map_payload({
        "schema_version": 1,
        "updated_at": "2026-05-15T00:01:00Z",
        "entries": {
            "01HID": {
                "alias": "new",
                "status": "garbage",
                "activated_at": None,
            },
        },
    })

    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.delete = MagicMock()
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/alias-map-old", [
            _meta("type", string_value="alias_map"),
            _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=old_chunks),
        ]),
        _doc("docs/alias-map-new", [
            _meta("type", string_value="alias_map"),
            _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=newer_invalid_chunks),
        ]),
    ])

    caplog.set_level("WARNING", logger="app.services.criteria_alias_map_service")
    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")

    with pytest.raises(AliasMapParseError) as exc_info:
        await svc.fetch()

    assert exc_info.value.doc_name == "docs/alias-map-new"
    assert "alias_map parse failed" in caplog.text
    client.file_search_stores.documents.delete.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_raises_when_unparseable_duplicate_has_unknown_updated_at():
    old_chunks = _alias_map_chunks("2026-05-15T00:00:00Z", "old")

    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.delete = MagicMock()
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/alias-map-old", [
            _meta("type", string_value="alias_map"),
            _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=old_chunks),
        ]),
        _doc("docs/alias-map-corrupt", [
            _meta("type", string_value="alias_map"),
            _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=["not-base64"]),
        ]),
    ])

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")

    with pytest.raises(AliasMapParseError) as exc_info:
        await svc.fetch()

    assert exc_info.value.doc_name == "docs/alias-map-corrupt"
    client.file_search_stores.documents.delete.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_raises_parse_error_for_corrupted_payload():
    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/alias-map", [
            _meta("type", string_value="alias_map"),
            _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=["e2ludmFsaWQ="]),
        ]),
    ])

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")

    with pytest.raises(AliasMapParseError) as exc_info:
        await svc.fetch()

    assert exc_info.value.doc_name == "docs/alias-map"
