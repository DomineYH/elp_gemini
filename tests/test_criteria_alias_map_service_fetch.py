"""alias-map 문서 fetch & parse — type=alias_map 만 인식"""

import time
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.alias_map_codec import (
    ALIAS_MAP_PAYLOAD_KEY,
    encode_alias_map_payload,
)
from app.services.criteria_alias_map_service import (
    AliasMapParseError,
    CriteriaAliasMapService,
    _read_metadata_kv,
)


def _meta(key, *, string_value=None, string_list_value=None):
    m = MagicMock()
    m.key = key
    m.string_value = string_value
    m.string_list_value = (
        MagicMock(values=string_list_value)
        if string_list_value is not None
        else None
    )
    return m


def _doc(name, metas):
    d = MagicMock()
    d.name = name
    d.custom_metadata = metas
    return d


def _alias_map_chunks(updated_at, alias):
    return encode_alias_map_payload(
        {
            "schema_version": 1,
            "updated_at": updated_at,
            "entries": {
                "01HID": {
                    "alias": alias,
                    "status": "uploaded",
                    "activated_at": None,
                },
            },
        }
    )


def test_read_metadata_kv_accepts_dict_string_list_value():
    kv = _read_metadata_kv(
        [
            {
                "key": "payload",
                "string_value": "a",
                "string_list_value": {"values": ["a", "b"]},
            }
        ]
    )

    assert kv["payload"] == ("a", ["a", "b"])


@pytest.mark.asyncio
async def test_fetch_returns_none_when_no_alias_map_doc():
    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.list.return_value = iter(
        [
            _doc("docs/a", [_meta("type", string_value="criteria")]),
        ]
    )

    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )
    result = await svc.fetch()
    assert result is None


@pytest.mark.asyncio
async def test_fetch_parses_payload_chunks():
    payload = {
        "schema_version": 1,
        "updated_at": "2026-05-15T00:00:00Z",
        "entries": {
            "01HID": {"alias": "한글", "status": "active", "activated_at": None}
        },
    }
    chunks = encode_alias_map_payload(payload)

    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.list.return_value = iter(
        [
            _doc(
                "docs/alias-map",
                [
                    _meta("type", string_value="alias_map"),
                    _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=chunks),
                ],
            ),
        ]
    )

    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )
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
    client.file_search_stores.documents.list.return_value = iter(
        [
            _doc(
                "docs/alias-map-old",
                [
                    _meta("type", string_value="alias_map"),
                    _meta(
                        ALIAS_MAP_PAYLOAD_KEY,
                        string_list_value=_alias_map_chunks(
                            "2026-05-15T00:00:00Z", "old"
                        ),
                    ),
                ],
            ),
            _doc(
                "docs/alias-map-new",
                [
                    _meta("type", string_value="alias_map"),
                    _meta(
                        ALIAS_MAP_PAYLOAD_KEY,
                        string_list_value=_alias_map_chunks(
                            "2026-05-15T00:01:00Z", "new"
                        ),
                    ),
                ],
            ),
        ]
    )

    caplog.set_level(
        "WARNING", logger="app.services.criteria_alias_map_service"
    )
    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )

    fetched = await svc.fetch()

    assert fetched is not None
    doc_name, alias_map = fetched
    assert doc_name == "docs/alias-map-new"
    assert alias_map.entries["01HID"].alias == "new"
    assert "multiple alias_map documents" in caplog.text
    client.file_search_stores.documents.delete.assert_called_once_with(
        name="docs/alias-map-old",
        config={"force": True},
    )


@pytest.mark.asyncio
async def test_fetch_raises_when_newest_alias_map_is_unparseable(caplog):
    old_chunks = _alias_map_chunks("2026-05-15T00:00:00Z", "old")
    newer_invalid_chunks = encode_alias_map_payload(
        {
            "schema_version": 1,
            "updated_at": "2026-05-15T00:01:00Z",
            "entries": {
                "01HID": {
                    "alias": "new",
                    "status": "garbage",
                    "activated_at": None,
                },
            },
        }
    )

    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.delete = MagicMock()
    client.file_search_stores.documents.list.return_value = iter(
        [
            _doc(
                "docs/alias-map-old",
                [
                    _meta("type", string_value="alias_map"),
                    _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=old_chunks),
                ],
            ),
            _doc(
                "docs/alias-map-new",
                [
                    _meta("type", string_value="alias_map"),
                    _meta(
                        ALIAS_MAP_PAYLOAD_KEY,
                        string_list_value=newer_invalid_chunks,
                    ),
                ],
            ),
        ]
    )

    caplog.set_level(
        "WARNING", logger="app.services.criteria_alias_map_service"
    )
    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )

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
    client.file_search_stores.documents.list.return_value = iter(
        [
            _doc(
                "docs/alias-map-old",
                [
                    _meta("type", string_value="alias_map"),
                    _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=old_chunks),
                ],
            ),
            _doc(
                "docs/alias-map-corrupt",
                [
                    _meta("type", string_value="alias_map"),
                    _meta(
                        ALIAS_MAP_PAYLOAD_KEY, string_list_value=["not-base64"]
                    ),
                ],
            ),
        ]
    )

    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )

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
    client.file_search_stores.documents.list.return_value = iter(
        [
            _doc(
                "docs/alias-map",
                [
                    _meta("type", string_value="alias_map"),
                    _meta(
                        ALIAS_MAP_PAYLOAD_KEY,
                        string_list_value=["e2ludmFsaWQ="],
                    ),
                ],
            ),
        ]
    )

    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )

    with pytest.raises(AliasMapParseError) as exc_info:
        await svc.fetch()

    assert exc_info.value.doc_name == "docs/alias-map"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_valid_doc", [False, True])
async def test_parse_error_carries_every_unreadable_document(with_valid_doc):
    """#471: 복구가 못 읽는 문서를 한 번에 모두 지울 수 있어야 한다."""

    def alias_doc(name, chunks):
        return _doc(
            name,
            [
                _meta("type", string_value="alias_map"),
                _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=chunks),
            ],
        )

    docs = [
        alias_doc("docs/bad-1", ["not-base64"]),
        alias_doc("docs/bad-2", []),
    ]
    if with_valid_doc:
        docs.insert(
            0,
            alias_doc(
                "docs/valid", _alias_map_chunks("2026-05-15T00:00:00Z", "v")
            ),
        )
    client = MagicMock()
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.list.return_value = iter(docs)

    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )
    with pytest.raises(AliasMapParseError) as exc_info:
        await svc.fetch()

    assert exc_info.value.doc_name == "docs/bad-1"
    assert exc_info.value.doc_names == ["docs/bad-1", "docs/bad-2"]
    assert str(exc_info.value).startswith(
        "alias_map parse failed for docs/bad-1: "
    )
    assert AliasMapParseError("docs/one", ValueError("x")).doc_names == [
        "docs/one"
    ]


# 조회 GET 은 요청별 10초 제한과 일시 오류 재시도를 받고, 쓰기는 다시 부르지 않는다 (#465)
def _rubric_store():
    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"
    return store


def _alias_doc():
    return _doc(
        "docs/alias-map",
        [
            _meta("type", string_value="alias_map"),
            _meta(
                ALIAS_MAP_PAYLOAD_KEY,
                string_list_value=_alias_map_chunks(
                    "2026-05-15T00:00:00Z", "a"
                ),
            ),
        ],
    )


def _failing_then(n_fail, value, make=lambda: httpx.ReadTimeout("timed out")):
    calls = []

    def call(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) <= n_fail:
            raise make()
        return value()

    return call, calls


def _midway_failing_pager(value):
    """첫 쪽은 내주고 다음 쪽 요청에서 끊기는 지연 순회."""

    def pages():
        yield from value()[:1]
        raise httpx.RemoteProtocolError("Server disconnected")

    return pages


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


@pytest.mark.asyncio
@pytest.mark.parametrize("failing", ["stores", "docs"])
@pytest.mark.parametrize("n_fail", [0, 1, 3])
async def test_fetch_retries_only_failed_get(no_sleep, failing, n_fail):
    stores_value = lambda: [_rubric_store()]  # noqa: E731
    docs_value = lambda: [_alias_doc()]  # noqa: E731
    stores, store_calls = _failing_then(
        n_fail if failing == "stores" else 0, stores_value
    )
    docs, doc_calls = _failing_then(
        n_fail if failing == "docs" else 0, docs_value
    )
    client = MagicMock()
    client.file_search_stores.list.side_effect = stores
    client.file_search_stores.documents.list.side_effect = docs
    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )

    if n_fail == 3:
        with pytest.raises(httpx.ReadTimeout):
            await svc.fetch()
    else:
        doc_name, _ = await svc.fetch()
        assert doc_name == "docs/alias-map"

    attempts = min(n_fail + 1, 3)
    if failing == "stores":
        expected = (attempts, 0 if n_fail == 3 else 1)
    else:
        expected = (1, attempts)
    assert (len(store_calls), len(doc_calls)) == expected
    timeout = {"http_options": {"timeout": 10_000}}
    assert all(c == {"config": timeout} for c in store_calls)
    assert all(
        c == {"parent": "stores/x", "config": timeout} for c in doc_calls
    )


@pytest.mark.asyncio
async def test_fetch_retries_docs_when_paging_breaks_midway(no_sleep):
    client = MagicMock()
    client.file_search_stores.list.return_value = [_rubric_store()]
    pages = _midway_failing_pager(lambda: [_alias_doc(), _alias_doc()])
    client.file_search_stores.documents.list.side_effect = [
        pages(),
        iter([_alias_doc()]),
    ]
    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )

    doc_name, _ = await svc.fetch()

    assert doc_name == "docs/alias-map"
    assert client.file_search_stores.list.call_count == 1
    assert client.file_search_stores.documents.list.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_write", ["upload", "delete"])
async def test_replace_write_failure_is_not_retried(no_sleep, failing_write):
    from app.schemas.alias_map import AliasMap

    client = MagicMock()
    client.file_search_stores.list.return_value = [_rubric_store()]
    upload = client.file_search_stores.upload_to_file_search_store
    delete = client.file_search_stores.documents.delete
    if failing_write == "upload":
        upload.side_effect = httpx.RemoteProtocolError("Server disconnected")
    else:
        upload.return_value = MagicMock(done=True, error=None)
        upload.return_value.response.document_name = "docs/new"
        delete.side_effect = httpx.RemoteProtocolError("Server disconnected")
    svc = CriteriaAliasMapService(
        client=client, store_display_name="rubric-store"
    )
    am = AliasMap(
        schema_version=1, updated_at="2026-05-15T00:00:00Z", entries={}
    )

    with pytest.raises(httpx.RemoteProtocolError):
        await svc.replace(am, old_doc_name="docs/old")

    assert upload.call_count == 1
    assert delete.call_count == (0 if failing_write == "upload" else 1)
    assert client.file_search_stores.list.call_args.kwargs == {
        "config": {"http_options": {"timeout": 10_000}}
    }
