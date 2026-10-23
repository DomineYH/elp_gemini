"""criteria 서브시스템의 동기 File Search 호출이 event loop를 막지 않는다 (#237)"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.schemas.alias_map import AliasMap
from app.services import criteria_alias_map_service as alias_mod
from app.services.alias_map_codec import (
    ALIAS_MAP_PAYLOAD_KEY,
    encode_alias_map_payload,
)
from app.services.criteria_alias_map_service import CriteriaAliasMapService
from app.services.criteria_legacy_migration import (
    LEGACY_METADATA_STORE_NAME,
    migrate_from_legacy_manifest,
)
from app.services.criteria_vector_service import CriteriaVectorService


def _slow(value):
    """0.5초 막은 뒤 value를 돌려주는 동기 SDK 호출 목"""

    def call(*args, **kwargs):
        time.sleep(0.5)
        return value

    return Mock(side_effect=call)


async def _ticks_while(coro):
    """coro가 도는 동안 0.05초 ticker가 몇 번 돌았는지 센다."""
    ticks = 0
    done = False

    async def run():
        nonlocal done
        try:
            return await coro
        finally:
            done = True

    async def ticker():
        nonlocal ticks
        while not done:
            await asyncio.sleep(0.05)
            ticks += 1

    result, _ = await asyncio.gather(run(), ticker())
    return result, ticks


def _store(display_name="rubric-store"):
    store = Mock(display_name=display_name)
    store.name = "fileSearchStores/rubric"
    return store


def _alias_doc(name, updated_at):
    chunks = encode_alias_map_payload(
        {"schema_version": 1, "updated_at": updated_at, "entries": {}}
    )
    doc = Mock()
    doc.name = name
    doc.custom_metadata = [
        {"key": "type", "string_value": "alias_map"},
        {
            "key": ALIAS_MAP_PAYLOAD_KEY,
            "string_list_value": {"values": chunks},
        },
    ]
    return doc


def _vector_service(client):
    service = CriteriaVectorService.__new__(CriteriaVectorService)
    service.file_search_service = Mock(client=client)
    service.store_name = "rubric-store"
    return service


@pytest.mark.asyncio
async def test_delete_criteria_does_not_block_loop():
    client = Mock()
    client.file_search_stores.documents.delete = _slow(None)

    result, ticks = await _ticks_while(
        _vector_service(client).delete_criteria("docs/d1")
    )

    assert result is True
    client.file_search_stores.documents.delete.assert_called_once_with(
        name="docs/d1", config={"force": True}
    )
    assert ticks >= 5


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_call", ["stores", "documents"])
async def test_list_criteria_documents_does_not_block_loop(slow_call):
    client = Mock()
    doc = Mock(display_name="기준", custom_metadata=None)
    doc.name = "docs/d1"
    stores, docs = Mock(return_value=[_store()]), Mock(return_value=[doc])
    if slow_call == "stores":
        stores = _slow([_store()])
    else:
        docs = _slow([doc])
    client.file_search_stores.list = stores
    client.file_search_stores.documents.list = docs

    result, ticks = await _ticks_while(
        _vector_service(client).list_document_ids()
    )

    assert result == ["docs/d1"]
    assert ticks >= 5


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_call", ["stores", "documents", "cleanup"])
async def test_alias_map_fetch_does_not_block_loop(slow_call):
    client = Mock()
    newest = _alias_doc("docs/new", "2026-10-02T00:00:00Z")
    stale = _alias_doc("docs/old", "2026-10-01T00:00:00Z")
    client.file_search_stores.list = Mock(return_value=[_store()])
    client.file_search_stores.documents.list = Mock(
        return_value=[newest, stale]
    )
    client.file_search_stores.documents.delete = Mock()
    target = {
        "stores": client.file_search_stores.list,
        "documents": client.file_search_stores.documents.list,
        "cleanup": client.file_search_stores.documents.delete,
    }[slow_call]
    target.side_effect = _slow(target.return_value).side_effect

    result, ticks = await _ticks_while(
        CriteriaAliasMapService(client, "rubric-store").fetch()
    )

    assert result[0] == "docs/new"
    client.file_search_stores.documents.delete.assert_called_once_with(
        name="docs/old", config={"force": True}
    )
    assert ticks >= 5


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_call", ["stores", "upload", "poll", "delete"])
async def test_alias_map_replace_does_not_block_loop(slow_call):
    client = Mock()
    pending = Mock(done=False)
    finished = Mock(done=True)
    finished.response.document_name = "docs/alias-new"
    client.file_search_stores.list = Mock(return_value=[_store()])
    client.file_search_stores.upload_to_file_search_store = Mock(
        return_value=pending
    )
    client.operations.get = Mock(return_value=finished)
    client.file_search_stores.documents.delete = Mock()
    target = {
        "stores": client.file_search_stores.list,
        "upload": client.file_search_stores.upload_to_file_search_store,
        "poll": client.operations.get,
        "delete": client.file_search_stores.documents.delete,
    }[slow_call]
    target.side_effect = _slow(target.return_value).side_effect
    alias_map = AliasMap(
        schema_version=1, updated_at="2026-10-02T00:00:00Z", entries={}
    )

    # polling의 2초 대기만 건너뛰고 to_thread는 실제로 쓴다.
    fake_asyncio = SimpleNamespace(
        sleep=AsyncMock(), to_thread=asyncio.to_thread
    )
    with patch.object(alias_mod, "asyncio", fake_asyncio):
        result, ticks = await _ticks_while(
            CriteriaAliasMapService(client, "rubric-store").replace(
                alias_map, "docs/alias-old"
            )
        )

    assert result == "docs/alias-new"
    client.operations.get.assert_called_once_with(pending)
    client.file_search_stores.documents.delete.assert_called_once_with(
        name="docs/alias-old", config={"force": True}
    )
    assert ticks >= 5


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_call", ["list", "delete"])
async def test_migrate_from_legacy_manifest_does_not_block_loop(slow_call):
    client = Mock()
    legacy = _store(LEGACY_METADATA_STORE_NAME)
    client.file_search_stores.list = Mock(return_value=[legacy])
    client.file_search_stores.delete = Mock()
    target = getattr(client.file_search_stores, slow_call)
    target.side_effect = _slow(target.return_value).side_effect
    app_state = Mock(get=AsyncMock(return_value=None), set=AsyncMock())

    _, ticks = await _ticks_while(
        migrate_from_legacy_manifest(client=client, app_state=app_state)
    )

    client.file_search_stores.delete.assert_called_once_with(
        name=legacy.name, config={"force": True}
    )
    app_state.set.assert_awaited_once()
    assert ticks >= 5
