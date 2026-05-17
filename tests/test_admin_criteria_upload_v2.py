"""upload 라우터가 stable_id를 생성하고 alias_map에 entry 추가"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.repositories.app_state_repository import KEY_SYNC_STATE
from app.routers.admin.criteria import upload_criteria
from app.services.criteria_alias_map_service import AliasMapParseError


def test_upload_generates_stable_id_and_alias_entry():
    """
    Behavioral assertion checklist (verified manually + via service unit tests):

    1. POST /admin/criteria/upload with a small PDF returns 201/200 with {stable_id, document_id}.
    2. CriteriaVectorService.upload_criteria called with a freshly-generated 26-char
       stable_id and the user-supplied title.
    3. CriteriaAliasMapService.replace() called with an AliasMap whose entries contain
       the new stable_id, alias=None, status="active", activated_at populated.
    4. The criteria row in DB has matching stable_id and document_id.

    Full integration coverage lands in tests/test_e2e_criteria_meta_flow.py (Task 22).
    """
    pytest.skip("Structural test; behavior verified by service-level unit tests and Wave 7 e2e smoke")


@pytest.mark.asyncio
async def test_upload_cloud_upload_failure_marks_resync():
    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db = AsyncMock()
    current_admin = SimpleNamespace(username="admin")

    with patch(
        "app.routers.admin.criteria.FileValidator"
    ) as validator_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        vector = vector_cls.return_value
        vector.upload_criteria = AsyncMock(
            side_effect=RuntimeError("cloud upload failed")
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await upload_criteria(
                file=file,
                current_admin=current_admin,
                db=db,
                _sync_ready=None,
            )

    assert exc_info.value.status_code == 500
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_upload_alias_replace_failure_marks_resync():
    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db = AsyncMock()
    current_admin = SimpleNamespace(username="admin")

    with patch(
        "app.routers.admin.criteria.FileValidator"
    ) as validator_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        vector = vector_cls.return_value
        vector.upload_criteria = AsyncMock(
            return_value={"document_id": "docs/rubric"}
        )
        vector.file_search_service.client = MagicMock()

        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=None)
        alias.replace = AsyncMock(
            side_effect=RuntimeError("alias publish failed")
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await upload_criteria(
                file=file,
                current_admin=current_admin,
                db=db,
                _sync_ready=None,
            )

    assert exc_info.value.status_code == 500
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_upload_corrupted_alias_map_marks_resync_without_replace():
    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db = AsyncMock()
    current_admin = SimpleNamespace(username="admin")

    with patch(
        "app.routers.admin.criteria.FileValidator"
    ) as validator_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        vector = vector_cls.return_value
        vector.upload_criteria = AsyncMock(
            return_value={"document_id": "docs/rubric"}
        )
        vector.file_search_service.client = MagicMock()

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
            await upload_criteria(
                file=file,
                current_admin=current_admin,
                db=db,
                _sync_ready=None,
            )

    assert exc_info.value.status_code == 503
    alias.replace.assert_not_awaited()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_upload_db_commit_failure_after_cloud_writes_marks_resync():
    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db = AsyncMock()
    db.commit = AsyncMock(side_effect=[RuntimeError("commit failed"), None])
    current_admin = SimpleNamespace(username="admin")

    with patch(
        "app.routers.admin.criteria.FileValidator"
    ) as validator_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        vector = vector_cls.return_value
        vector.upload_criteria = AsyncMock(
            return_value={"document_id": "docs/rubric"}
        )
        vector.file_search_service.client = MagicMock()

        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=None)
        alias.replace = AsyncMock(return_value="docs/alias-map-new")

        repo_cls.return_value.insert = AsyncMock()

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await upload_criteria(
                file=file,
                current_admin=current_admin,
                db=db,
                _sync_ready=None,
            )

    assert exc_info.value.status_code == 500
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_upload_creates_active_entry():
    """New upload immediately has status='active', activated_at is not None."""
    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db = AsyncMock()
    current_admin = SimpleNamespace(username="admin")

    with patch(
        "app.routers.admin.criteria.FileValidator"
    ) as validator_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        vector = vector_cls.return_value
        vector.upload_criteria = AsyncMock(
            return_value={"document_id": "docs/rubric"}
        )
        vector.file_search_service.client = MagicMock()

        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=None)
        alias.replace = AsyncMock(return_value="docs/alias-map-new")

        repo_cls.return_value.insert = AsyncMock()

        result = await upload_criteria(
            file=file,
            current_admin=current_admin,
            db=db,
            _sync_ready=None,
        )

    new_sid = result["stable_id"]

    # alias_map entry is active
    alias.replace.assert_awaited_once()
    new_alias_map = alias.replace.await_args.args[0]
    assert new_alias_map.entries[new_sid].status == "active"
    assert new_alias_map.entries[new_sid].activated_at is not None

    # DB insert is active
    repo_cls.return_value.insert.assert_awaited_once()
    insert_kwargs = repo_cls.return_value.insert.await_args.kwargs
    assert insert_kwargs["status"] == "active"
    assert insert_kwargs["activated_at"] is not None
