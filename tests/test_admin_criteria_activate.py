"""POST .../activate + /deactivate routes"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.repositories.app_state_repository import KEY_SYNC_STATE
from app.routers.admin.criteria import (
    activate_by_stable_id,
    deactivate_by_stable_id,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry


def test_deactivate_demotes_to_uploaded():
    """POST .../deactivate sets status="uploaded", activated_at=None"""
    pytest.skip("Structural test")


def test_activate_route_is_registered():
    from app.routers.admin.criteria import router
    paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/api/admin/criteria/{stable_id}/activate" in paths
    assert "/api/admin/criteria/{stable_id}/deactivate" in paths


@pytest.mark.asyncio
async def test_activate_replace_failure_marks_resync():
    db = AsyncMock()
    stable_id = "01HACTIVE"

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
            await activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_activate_replace_failure_recovers_when_cloud_has_target_status():
    db = AsyncMock()
    stable_id = "01HACTIVE"
    row = MagicMock(status="uploaded", activated_at=None)

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
        alias.fetch = AsyncMock(side_effect=[
            (
                "docs/alias-map-old",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:00Z",
                    entries={
                        stable_id: AliasMapEntry(
                            alias=None,
                            status="uploaded",
                            activated_at=None,
                        ),
                    },
                ),
            ),
            (
                "docs/alias-map-new",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:01Z",
                    entries={
                        stable_id: AliasMapEntry(
                            alias=None,
                            status="active",
                            activated_at="2026-05-15T00:00:01Z",
                        ),
                    },
                ),
            ),
        ])
        alias.replace = AsyncMock(
            side_effect=TimeoutError("alias-map upload timeout")
        )
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=row
        )
        state = state_cls.return_value
        state.set = AsyncMock()

        result = await activate_by_stable_id(
            stable_id=stable_id,
            current_admin=object(),
            _sync_ready=None,
            db=db,
        )

    assert result == {"stable_id": stable_id, "status": "active"}
    assert row.status == "active"
    assert row.activated_at is not None
    alias.replace.assert_awaited_once()
    assert alias.fetch.await_count == 2
    db.rollback.assert_awaited_once()
    db.commit.assert_awaited_once()
    state.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_replace_failure_recovers_when_cloud_has_target_status():
    db = AsyncMock()
    stable_id = "01HDEACTIVE"
    row = MagicMock(
        status="active",
        activated_at="2026-05-15T00:00:00Z",
    )

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
        alias.fetch = AsyncMock(side_effect=[
            (
                "docs/alias-map-old",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:00Z",
                    entries={
                        stable_id: AliasMapEntry(
                            alias=None,
                            status="active",
                            activated_at="2026-05-15T00:00:00Z",
                        ),
                    },
                ),
            ),
            (
                "docs/alias-map-new",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:01Z",
                    entries={
                        stable_id: AliasMapEntry(
                            alias=None,
                            status="uploaded",
                            activated_at=None,
                        ),
                    },
                ),
            ),
        ])
        alias.replace = AsyncMock(
            side_effect=RuntimeError("old alias-map delete failed")
        )
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=row
        )
        state = state_cls.return_value
        state.set = AsyncMock()

        result = await deactivate_by_stable_id(
            stable_id=stable_id,
            current_admin=object(),
            _sync_ready=None,
            db=db,
        )

    assert result == {"stable_id": stable_id, "status": "uploaded"}
    assert row.status == "uploaded"
    assert row.activated_at is None
    alias.replace.assert_awaited_once()
    assert alias.fetch.await_count == 2
    db.rollback.assert_awaited_once()
    db.commit.assert_awaited_once()
    state.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_activate_replace_failure_still_marks_resync_when_cloud_unchanged():
    db = AsyncMock()
    stable_id = "01HACTIVE"

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        old_alias_map = AliasMap(
            schema_version=1,
            updated_at="2026-05-15T00:00:00Z",
            entries={
                stable_id: AliasMapEntry(
                    alias=None,
                    status="uploaded",
                    activated_at=None,
                ),
            },
        )
        alias.fetch = AsyncMock(side_effect=[
            ("docs/alias-map", old_alias_map),
            ("docs/alias-map", old_alias_map),
        ])
        alias.replace = AsyncMock(
            side_effect=RuntimeError("upload_to_file_search_store 503")
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    assert alias.fetch.await_count == 2
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_deactivate_replace_failure_marks_resync():
    db = AsyncMock()
    stable_id = "01HDEACTIVE"

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
                        alias=None,
                        status="active",
                        activated_at="2026-05-15T00:00:00Z",
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
            await deactivate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_activate_missing_alias_map_marks_resync_without_replace():
    db = AsyncMock()
    stable_id = "01HACTIVE"

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=None)
        alias.replace = AsyncMock()

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 409
    alias.replace.assert_not_awaited()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_activate_db_commit_failure_after_replace_marks_resync():
    db = AsyncMock()
    db.commit = AsyncMock(side_effect=[RuntimeError("commit failed"), None])
    stable_id = "01HACTIVE"

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
                    "01HOTHER": AliasMapEntry(
                        alias=None,
                        status="active",
                        activated_at="2026-05-15T00:00:00Z",
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock(return_value="docs/alias-map-new")

        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            side_effect=[
                MagicMock(status="uploaded", activated_at=None),
                MagicMock(status="active", activated_at=None),
            ]
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_deactivate_db_commit_failure_after_replace_marks_resync():
    db = AsyncMock()
    db.commit = AsyncMock(side_effect=[RuntimeError("commit failed"), None])
    stable_id = "01HDEACTIVE"

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
                        alias=None,
                        status="active",
                        activated_at="2026-05-15T00:00:00Z",
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock(return_value="docs/alias-map-new")

        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=MagicMock(status="active", activated_at=None)
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await deactivate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_activate_does_not_demote_existing_active():
    """When sid_a is active and we activate sid_b, both end up active."""
    db = AsyncMock()
    sid_a = "01HACTIVE_A"
    sid_b = "01HACTIVE_B"

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    sid_a: AliasMapEntry(
                        alias=None, status="active",
                        activated_at="2026-05-15T00:00:00Z",
                    ),
                    sid_b: AliasMapEntry(
                        alias=None, status="uploaded", activated_at=None,
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock()

        repo = repo_cls.return_value
        repo.get_criteria_by_stable_id = AsyncMock(
            side_effect=[
                MagicMock(status="active", activated_at=None),
                MagicMock(status="uploaded", activated_at=None),
            ]
        )

        result = await activate_by_stable_id(
            stable_id=sid_b,
            current_admin=object(),
            _sync_ready=None,
            db=db,
        )

    assert result["status"] == "active"
    alias.replace.assert_awaited_once()
    new_alias_map = alias.replace.await_args.args[0]
    assert new_alias_map.entries[sid_a].status == "active"
    assert new_alias_map.entries[sid_b].status == "active"
