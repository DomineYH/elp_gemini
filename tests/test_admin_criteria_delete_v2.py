"""DELETE /admin/criteria/{stable_id}"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.repositories.app_state_repository import KEY_SYNC_STATE
from app.routers.admin.criteria import delete_criteria_by_stable_id
from app.schemas.alias_map import AliasMap, AliasMapEntry


def test_delete_removes_cloud_alias_and_db():
    """
    Behavioral checklist:
    1. DELETE /admin/criteria/{stable_id} returns 200 with {stable_id, deleted:true}.
    2. CriteriaVectorService.delete_criteria(document_id) called once.
    3. CriteriaAliasMapService.replace() called with entries minus the deleted stable_id.
    4. DB row for stable_id is removed.
    """
    pytest.skip("Structural test; covered by service tests + e2e")


def test_delete_route_is_registered():
    from app.routers.admin.criteria import router
    routes_by_method = [(r.path, sorted(getattr(r, "methods", set()) or set())) for r in router.routes if hasattr(r, "path")]
    delete_routes = [(p, m) for p, m in routes_by_method if "DELETE" in m]
    # The new stable_id route should exist:
    assert any("/{stable_id}" in p for p, _ in delete_routes), f"DELETE /{{stable_id}} not registered. Routes: {delete_routes}"


@pytest.mark.asyncio
async def test_delete_cloud_delete_failure_marks_resync():
    stable_id = "01HDELETE"
    row = SimpleNamespace(stable_id=stable_id, document_id="docs/rubric")
    db = AsyncMock()

    with patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=row
        )

        vector = vector_cls.return_value
        vector.delete_criteria = AsyncMock(
            side_effect=RuntimeError("cloud delete failed")
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await delete_criteria_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    vector.delete_criteria.assert_awaited_once_with(document_id="docs/rubric")
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_delete_alias_replace_failure_marks_resync():
    stable_id = "01HDELETE"
    row = SimpleNamespace(stable_id=stable_id, document_id="docs/rubric")
    db = AsyncMock()

    with patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=row
        )

        vector = vector_cls.return_value
        vector.delete_criteria = AsyncMock(return_value=True)
        vector.file_search_service.client = MagicMock()

        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    stable_id: AliasMapEntry(
                        alias=None, status="uploaded", activated_at=None
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock(
            side_effect=RuntimeError("alias publish failed")
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await delete_criteria_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_delete_db_commit_failure_after_cloud_writes_marks_resync():
    stable_id = "01HDELETE"
    row = SimpleNamespace(stable_id=stable_id, document_id="docs/rubric")
    db = AsyncMock()
    db.commit = AsyncMock(side_effect=[RuntimeError("commit failed"), None])

    with patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=row
        )

        vector = vector_cls.return_value
        vector.delete_criteria = AsyncMock(return_value=True)
        vector.file_search_service.client = MagicMock()

        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    stable_id: AliasMapEntry(
                        alias=None, status="uploaded", activated_at=None
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock(return_value="docs/alias-map-new")

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await delete_criteria_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    vector.delete_criteria.assert_awaited_once_with(document_id="docs/rubric")
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")
