"""upload 라우터가 stable_id를 생성하고 alias_map에 entry 추가"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from google.genai import errors as genai_errors

from app.repositories.app_state_repository import KEY_SYNC_STATE
from app.routers.admin.criteria import upload_criteria
from app.services.criteria_alias_map_service import AliasMapParseError


def test_upload_generates_stable_id_and_alias_entry():
    """
    Behavioral assertion checklist (verified manually + via service unit tests):

    1. Small-PDF upload returns 201/200 with stable_id and document_id.
    2. CriteriaVectorService.upload_criteria receives a generated stable_id.
    3. CriteriaAliasMapService.replace() receives an active alias_map entry.
    4. The criteria row in DB has matching stable_id and document_id.

    Integration coverage lives in tests/test_e2e_criteria_meta_flow.py.
    """
    pytest.skip("Structural test; covered by service-level units and e2e smoke")


@pytest.mark.asyncio
async def test_upload_cloud_upload_failure_marks_resync():
    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db = AsyncMock()
    current_admin = SimpleNamespace(username="admin")

    with (
        patch("app.routers.admin.criteria.FileValidator") as validator_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
    ):
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

    with (
        patch("app.routers.admin.criteria.FileValidator") as validator_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
    ):
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

    with (
        patch("app.routers.admin.criteria.FileValidator") as validator_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
    ):
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

    with (
        patch("app.routers.admin.criteria.FileValidator") as validator_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
        patch("app.routers.admin.criteria.CriteriaRepository") as repo_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
    ):
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

    with (
        patch("app.routers.admin.criteria.FileValidator") as validator_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
        patch("app.routers.admin.criteria.CriteriaRepository") as repo_cls,
    ):
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
    # 올린 바이트 수를 저장한다 (#446)
    assert insert_kwargs["file_size"] == len(b"%PDF-1.4 rubric")


@pytest.mark.asyncio
async def test_upload_poll_connection_error_hides_message(caplog):
    """폴링 연결 오류 원문이 500 응답, sync_error 저장값, 오류 로그 traceback에
    들어가지 않는다 (#373)."""
    import logging

    import httpx

    from app.repositories.app_state_repository import KEY_SYNC_ERROR
    from app.services import operation_polling

    marker = "x-goog-api-key: SECRET-MARKER"
    client = MagicMock()
    client.aio.operations.get = AsyncMock(
        side_effect=[httpx.RemoteProtocolError(marker) for _ in range(3)]
    )

    async def upload_criteria_via_poll(*args, **kwargs):
        await operation_polling.poll_operation(
            client,
            SimpleNamespace(done=False),
            deadline_s=300,
            interval_s=5,
            label="파일 업로드 rubric.pdf",
        )

    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    with (
        patch.object(operation_polling, "_sleep", AsyncMock()),
        patch("app.routers.admin.criteria.FileValidator") as validator_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
    ):
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        vector_cls.return_value.upload_criteria = AsyncMock(
            side_effect=upload_criteria_via_poll
        )
        state = state_cls.return_value
        state.set = AsyncMock()

        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(HTTPException) as exc_info,
        ):
            await upload_criteria(
                file=file,
                current_admin=SimpleNamespace(username="admin"),
                db=AsyncMock(),
                _sync_ready=None,
            )

    assert exc_info.value.status_code == 500
    assert "SECRET-MARKER" not in exc_info.value.detail
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors
    rendered = "\n".join(logging.Formatter().format(r) for r in errors)
    assert "SECRET-MARKER" not in rendered
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")
    stored = [
        c.args[1]
        for c in state.set.await_args_list
        if c.args[0] == KEY_SYNC_ERROR
    ]
    assert stored and all("SECRET-MARKER" not in v for v in stored)


_MARKER = "sensitive-marker"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make, detail, stored, traceback_logged",
    [
        (
            lambda: httpx.ConnectError(_MARKER),
            "ConnectError",
            "ConnectError",
            False,
        ),
        (
            lambda: genai_errors.ClientError(
                403, {"error": {"code": 403, "message": _MARKER}}
            ),
            "ClientError 403",
            "ClientError 403",
            False,
        ),
        # 앱이 만든 글은 그대로 나가고 traceback 도 남는다
        (
            lambda: RuntimeError("파일 업로드 rubric.pdf: 작업 실패: boom"),
            "RuntimeError - 파일 업로드 rubric.pdf: 작업 실패: boom",
            "파일 업로드 rubric.pdf: 작업 실패: boom",
            True,
        ),
    ],
    ids=["transport", "sdk403", "app"],
)
async def test_upload_failure_500_hides_raw_error_text(
    caplog, make, detail, stored, traceback_logged
):
    """#485: 업로드 500 detail·저장값·로그에 전송/SDK 오류 원문이 없다."""
    from app.repositories.app_state_repository import KEY_SYNC_ERROR

    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    with (
        patch("app.routers.admin.criteria.FileValidator") as validator_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
    ):
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        vector_cls.return_value.upload_criteria = AsyncMock(side_effect=make())
        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await upload_criteria(
                file=file,
                current_admin=SimpleNamespace(username="admin"),
                db=AsyncMock(),
                _sync_ready=None,
            )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == (
        f"파일 업로드 중 오류가 발생했습니다: {detail}"
    )
    state.set.assert_any_await(KEY_SYNC_ERROR, stored)
    assert _MARKER not in caplog.text
    assert f"메시지: {stored}" in caplog.text
    assert ("Traceback" in caplog.text) is traceback_logged
