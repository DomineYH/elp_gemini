"""legacy migration: manifest → alias_map + metadata-store 삭제"""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_no_op_when_migration_marker_set():
    from app.services.criteria_legacy_migration import migrate_from_legacy_manifest

    state = MagicMock()
    state.get = AsyncMock(return_value="true")  # marker present
    client = MagicMock()
    state.set = AsyncMock()

    await migrate_from_legacy_manifest(client=client, app_state=state)

    client.file_search_stores.list.assert_not_called()


@pytest.mark.asyncio
async def test_no_op_when_legacy_store_absent():
    from app.services.criteria_legacy_migration import migrate_from_legacy_manifest

    state = MagicMock()
    state.get = AsyncMock(return_value=None)
    state.set = AsyncMock()

    client = MagicMock()
    rubric_store = MagicMock()
    rubric_store.name = "stores/r"
    rubric_store.display_name = "rubric-store"
    client.file_search_stores.list.return_value = iter([rubric_store])

    await migrate_from_legacy_manifest(client=client, app_state=state)

    state.set.assert_called_once_with("criteria_migration_v2_done", "true")


@pytest.mark.asyncio
async def test_deletes_legacy_store_and_sets_marker():
    from app.services.criteria_legacy_migration import migrate_from_legacy_manifest

    state = MagicMock()
    state.get = AsyncMock(return_value=None)
    state.set = AsyncMock()

    legacy_store = MagicMock()
    legacy_store.name = "stores/legacy"
    legacy_store.display_name = "rubric-metadata-store"
    rubric_store = MagicMock()
    rubric_store.name = "stores/r"
    rubric_store.display_name = "rubric-store"

    client = MagicMock()
    client.file_search_stores.list.return_value = iter([rubric_store, legacy_store])
    client.file_search_stores.delete = MagicMock()

    await migrate_from_legacy_manifest(client=client, app_state=state)

    client.file_search_stores.delete.assert_called_once_with(
        name="stores/legacy", config={"force": True}
    )
    state.set.assert_called_once_with("criteria_migration_v2_done", "true")
