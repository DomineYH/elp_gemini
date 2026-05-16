"""PATCH /admin/criteria/{stable_id}/alias"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.repositories.app_state_repository import KEY_SYNC_STATE
from app.routers.admin.criteria import _AliasPatch, patch_criteria_alias
from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_alias_map_service import AliasMapParseError


def test_patch_alias_updates_alias_map_and_db():
    """
    Behavioral checklist (verified via service-level tests + Wave 7 e2e):
    1. PATCH /admin/criteria/{stable_id}/alias with body {alias: "..."} returns 200.
    2. CriteriaAliasMapService.replace() called with updated entries.alias.
    3. DB row for stable_id has display_alias updated.
    4. PDF is NOT re-uploaded (no upload_to_file_search_store call besides alias-map).
    """
    pytest.skip("Structural test; covered by Wave 2 service tests + Wave 7 e2e")


def test_patch_alias_route_is_registered():
    """Verify the new PATCH route is wired into the FastAPI router."""
    from app.routers.admin.criteria import router
    paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/api/admin/criteria/{stable_id}/alias" in paths


@pytest.mark.asyncio
async def test_patch_alias_replace_failure_marks_resync():
    db = AsyncMock()
    stable_id = "01HALIAS"

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
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
            await patch_criteria_alias(
                stable_id=stable_id,
                body=_AliasPatch(alias="new alias"),
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_patch_alias_corrupted_alias_map_marks_resync_without_replace():
    db = AsyncMock()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(
            side_effect=AliasMapParseError(
                "docs/alias-map", ValueError("bad payload")
            )
        )
        alias.replace = AsyncMock()

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_criteria_alias(
                stable_id="01HALIAS",
                body=_AliasPatch(alias="new alias"),
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 503
    alias.replace.assert_not_awaited()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_patch_alias_db_commit_failure_after_replace_marks_resync():
    db = AsyncMock()
    db.commit = AsyncMock(side_effect=[RuntimeError("commit failed"), None])
    stable_id = "01HALIAS"

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
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

        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=MagicMock(display_alias=None)
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_criteria_alias(
                stable_id=stable_id,
                body=_AliasPatch(alias="new alias"),
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")
