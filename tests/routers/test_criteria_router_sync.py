# tests/routers/test_criteria_router_sync.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from google.genai import errors as genai_errors

from app.routers.admin.criteria import (
    activate_by_stable_id,
    delete_criteria_by_stable_id,
    list_criteria_json,
    reconcile_criteria,
    router,
    upload_criteria,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry


@pytest.mark.asyncio
async def test_reconcile_endpoint_returns_state():
    mock_result = type(
        "R", (), {"ok": True, "skipped": False, "count": 2, "error": None}
    )()

    with (
        patch(
            "app.routers.admin.criteria.CriteriaReconciliationService"
        ) as svc_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as repo_cls,
    ):
        instance = svc_cls.return_value
        instance.reconcile = AsyncMock(return_value=mock_result)
        mock_state = AsyncMock()
        mock_state.get = AsyncMock(return_value="ok")
        repo_cls.return_value = mock_state

        body = await reconcile_criteria(db=object(), _admin=object())

    assert body["ok"] is True
    assert body["count"] == 2


@pytest.mark.asyncio
async def test_list_endpoint_includes_sync_metadata():
    with (
        patch("app.routers.admin.criteria.AppStateRepository") as repo_cls,
        patch("app.routers.admin.criteria.CriteriaRepository") as crit_cls,
    ):
        mock_state = AsyncMock()
        mock_state.get = AsyncMock(
            side_effect=lambda k: {
                "criteria_sync_state": "ok",
                "criteria_last_synced_at": "2026-05-15T00:00Z",
                "criteria_sync_error": None,
            }.get(k)
        )
        repo_cls.return_value = mock_state
        crit_instance = crit_cls.return_value
        crit_instance.get_all_criteria = AsyncMock(return_value=[])

        body = await list_criteria_json(current_admin=object(), db=object())

    assert "sync" in body
    assert body["sync"]["state"] == "ok"


@pytest.mark.asyncio
async def test_list_criteria_json_includes_id_and_stable_id():
    row = SimpleNamespace(
        id=7,
        stable_id="01HJSONSTABLE",
        title="rubric.pdf",
        display_alias=None,
        status="uploaded",
        file_size=123,
        created_at=None,
        document_id="fileSearchStores/s/documents/rubric",
    )

    with (
        patch("app.routers.admin.criteria.AppStateRepository") as repo_cls,
        patch("app.routers.admin.criteria.CriteriaRepository") as crit_cls,
    ):
        mock_state = AsyncMock()
        mock_state.get = AsyncMock(return_value=None)
        repo_cls.return_value = mock_state
        crit_instance = crit_cls.return_value
        crit_instance.get_all_criteria = AsyncMock(return_value=[row])

        body = await list_criteria_json(current_admin=object(), db=object())

    item = body["criteria"][0]
    assert item["id"] == 7
    assert item["stable_id"] == "01HJSONSTABLE"


def test_upload_route_requires_sync_ready_dependency():
    from app.dependencies import require_criteria_sync_ready

    upload_route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/api/admin/criteria/upload"
        and "POST" in getattr(route, "methods", set())
    )
    assert any(
        dep.call is require_criteria_sync_ready
        for dep in upload_route.dependant.dependencies
    )


@pytest.mark.asyncio
async def test_activate_rejects_legacy_surrogate_stable_id():
    legacy_stable_id = "legacy_0123456789abcdef"
    db = AsyncMock()

    with (
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
        patch("app.routers.admin.criteria.CriteriaRepository") as repo_cls,
    ):
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias_cls.return_value.fetch = AsyncMock(
            return_value=(
                "docs/alias-map",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:00Z",
                    entries={
                        legacy_stable_id: AliasMapEntry(
                            alias=None, status="uploaded", activated_at=None
                        ),
                    },
                ),
            )
        )
        alias_cls.return_value.replace = AsyncMock()
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(
                stable_id=legacy_stable_id,
                status="uploaded",
                activated_at=None,
            )
        )

        with pytest.raises(HTTPException) as exc:
            await activate_by_stable_id(
                stable_id=legacy_stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc.value.status_code == 400
    assert "Legacy" in exc.value.detail
    assert "교체" in exc.value.detail
    # 옛 문구는 더 이상 안내되지 않음
    assert "삭제 후 다시 업로드" not in exc.value.detail


@pytest.mark.asyncio
async def test_delete_legacy_surrogate_uses_real_document_id():
    legacy_stable_id = "legacy_0123456789abcdef"
    real_document_id = "fileSearchStores/s/documents/pre-v2"
    row = SimpleNamespace(
        stable_id=legacy_stable_id,
        document_id=real_document_id,
    )
    db = AsyncMock()

    with (
        patch("app.routers.admin.criteria.CriteriaRepository") as repo_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
    ):
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=row
        )
        vector = vector_cls.return_value
        vector.delete_criteria = AsyncMock(return_value=True)
        vector.file_search_service.client = MagicMock()
        alias_cls.return_value.fetch = AsyncMock(
            return_value=(
                "docs/alias-map",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:00Z",
                    entries={
                        legacy_stable_id: AliasMapEntry(
                            alias=None, status="uploaded", activated_at=None
                        ),
                    },
                ),
            )
        )
        alias_cls.return_value.replace = AsyncMock()

        body = await delete_criteria_by_stable_id(
            stable_id=legacy_stable_id,
            current_admin=object(),
            _sync_ready=None,
            db=db,
        )

    assert body == {"stable_id": legacy_stable_id, "deleted": True}
    vector.delete_criteria.assert_awaited_once_with(
        document_id=real_document_id
    )
    db.delete.assert_awaited_once_with(row)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_does_not_publish_manifest_before_cloud_document_exists():
    pytest.skip(
        "Wave 5: replaced by new alias_map-based upload; assertions no longer apply"
    )
    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db = AsyncMock()
    current_admin = SimpleNamespace(username="admin")
    criteria = SimpleNamespace(id=123, file_path="temp")

    with (
        patch("app.routers.admin.criteria.FileValidator") as validator_cls,
        patch("app.routers.admin.criteria.CriteriaRepository") as repo_cls,
        patch(
            "app.services.file_storage_service.FileStorageService"
        ) as storage_cls,
        patch(
            "app.routers.admin.criteria._publish_or_mark_resync",
            new_callable=AsyncMock,
        ) as publish,
    ):
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        repo_cls.return_value.save_criteria = AsyncMock(return_value=criteria)
        storage_cls.return_value.save_file = MagicMock(
            return_value="/criteria/123_rubric.pdf"
        )

        response = await upload_criteria(
            file=file,
            current_admin=current_admin,
            db=db,
            _sync_ready=None,
        )

    assert response.file_id == "123"
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_needs_resync_stores_transport_error_type_not_message():
    """#469: 전송 오류 원문(헤더 값이 들어갈 수 있다)은 저장하지 않는다."""
    import httpx

    from app.repositories.app_state_repository import KEY_SYNC_ERROR
    from app.routers.admin.criteria import _mark_criteria_needs_resync

    db = AsyncMock()
    with patch("app.routers.admin.criteria.AppStateRepository") as state_cls:
        state = state_cls.return_value
        state.set = AsyncMock()
        await _mark_criteria_needs_resync(
            db,
            httpx.LocalProtocolError(
                "Illegal header value b'FAKE-KEY-MARKER\\n'"
            ),
        )

    state.set.assert_any_await(KEY_SYNC_ERROR, "LocalProtocolError")
    assert "FAKE-KEY-MARKER" not in str(state.set.await_args_list)


_MARKER = "sensitive-marker"
_FAILURES = [
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
    # 앱이 만든 글은 지금처럼 '종류 - 글'로 나가고 traceback 도 남는다
    (lambda: RuntimeError("boom"), "RuntimeError - boom", "boom", True),
]
_FAILURE_IDS = ["transport", "sdk403", "app"]


def _alias_map(status="uploaded"):
    return AliasMap(
        schema_version=1,
        updated_at="2026-05-15T00:00:00Z",
        entries={
            "SID": AliasMapEntry(alias=None, status=status, activated_at=None)
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make, detail, stored, traceback_logged", _FAILURES, ids=_FAILURE_IDS
)
async def test_delete_failure_500_hides_raw_error_text(
    caplog, make, detail, stored, traceback_logged
):
    """#485: 500 detail·저장값·로그에 전송/SDK 오류 원문이 없다."""
    from app.repositories.app_state_repository import KEY_SYNC_ERROR

    with (
        patch("app.routers.admin.criteria.CriteriaRepository") as repo_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
    ):
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(stable_id="SID", document_id="docs/d")
        )
        vector_cls.return_value.delete_criteria = AsyncMock(side_effect=make())
        alias_cls.return_value.fetch = AsyncMock(
            return_value=("docs/alias-map", _alias_map())
        )
        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await delete_criteria_by_stable_id(
                stable_id="SID",
                current_admin=object(),
                _sync_ready=None,
                db=AsyncMock(),
            )

    assert exc.value.status_code == 500
    assert exc.value.detail == f"평가기준 변경 중 오류가 발생했습니다: {detail}"
    state.set.assert_any_await(KEY_SYNC_ERROR, stored)
    assert _MARKER not in caplog.text
    assert f"평가기준 변경 실패: {stored}" in caplog.text
    assert ("Traceback" in caplog.text) is traceback_logged


@pytest.mark.asyncio
@pytest.mark.parametrize("recovered", [False, True])
async def test_activate_failure_recovery_logs_hide_raw_error_text(
    caplog, recovered
):
    """#485: 상태 변경 실패 뒤 재조회 실패·복구 안내 로그에도 원문이 없다."""
    published = []

    async def failing_replace(alias_map, old_doc_name=None):
        published.append(alias_map)
        raise httpx.ConnectError(_MARKER)

    async def fetch():
        if not published:
            return "docs/alias-map", _alias_map()
        if recovered:  # 쓰기는 실제로 반영됐다
            return "docs/alias-map-2", published[0]
        raise genai_errors.ClientError(
            403, {"error": {"code": 403, "message": _MARKER}}
        )

    with (
        patch("app.routers.admin.criteria.CriteriaRepository") as repo_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService"),
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
        caplog.at_level("INFO", logger="app.routers.admin.criteria"),
    ):
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=None
        )
        alias_cls.return_value.fetch = fetch
        alias_cls.return_value.replace = failing_replace
        state_cls.return_value.set = AsyncMock()
        call = activate_by_stable_id(
            stable_id="SID",
            current_admin=object(),
            _sync_ready=None,
            db=AsyncMock(),
        )
        if recovered:
            assert await call == {"stable_id": "SID", "status": "active"}
            assert "original_error=ConnectError" in caplog.text
        else:
            with pytest.raises(HTTPException) as exc:
                await call
            assert exc.value.detail == (
                "평가기준 변경 중 오류가 발생했습니다: ConnectError"
            )
            assert "alias_map 재조회 실패: ClientError 403" in caplog.text

    assert _MARKER not in caplog.text
    assert "Traceback" not in caplog.text


def _db_error():
    from sqlalchemy.exc import IntegrityError

    return IntegrityError(
        "INSERT INTO app_state (key, value) VALUES (?, ?)",
        ("criteria_sync_error", _MARKER),
        Exception("constraint"),
    )


@pytest.mark.asyncio
async def test_needs_resync_record_db_failure_hides_sql_params(caplog):
    """#485: needs_resync 기록 중 rollback·쓰기가 DB 오류로 실패해도 로그에 SQL 바인딩 값이 없다."""
    with (
        patch("app.routers.admin.criteria.CriteriaRepository") as repo_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService") as vector_cls,
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
    ):
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(stable_id="SID", document_id="docs/d")
        )
        vector_cls.return_value.delete_criteria = AsyncMock(
            side_effect=httpx.ConnectError(_MARKER)
        )
        alias_cls.return_value.fetch = AsyncMock(
            return_value=("docs/alias-map", _alias_map())
        )
        state_cls.return_value.set = AsyncMock(side_effect=_db_error())
        db = AsyncMock()
        db.rollback.side_effect = _db_error()

        with pytest.raises(HTTPException) as exc:
            await delete_criteria_by_stable_id(
                stable_id="SID",
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc.value.status_code == 500
    assert exc.value.detail == (
        "평가기준 변경 중 오류가 발생했습니다: ConnectError"
    )
    assert "rollback 실패: IntegrityError" in caplog.text
    assert "needs_resync 표시 실패: IntegrityError" in caplog.text
    assert _MARKER not in caplog.text


@pytest.mark.asyncio
async def test_activate_recovery_db_failure_hides_sql_params(caplog):
    """#485: 상태 변경 복구 중 rollback·DB 캐시 복구가 DB 오류로 실패해도 로그에 SQL 바인딩 값이 없다."""
    published = []

    async def failing_replace(alias_map, old_doc_name=None):
        published.append(alias_map)
        raise httpx.ConnectError(_MARKER)

    async def fetch():
        if not published:
            return "docs/alias-map", _alias_map()
        return "docs/alias-map-2", published[0]

    with (
        patch("app.routers.admin.criteria.CriteriaRepository") as repo_cls,
        patch("app.routers.admin.criteria.CriteriaVectorService"),
        patch(
            "app.routers.admin.criteria.CriteriaAliasMapService"
        ) as alias_cls,
        patch("app.routers.admin.criteria.AppStateRepository") as state_cls,
    ):
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=None
        )
        alias_cls.return_value.fetch = fetch
        alias_cls.return_value.replace = failing_replace
        state_cls.return_value.set = AsyncMock()
        db = AsyncMock()
        db.rollback.side_effect = _db_error()
        db.commit.side_effect = _db_error()

        with pytest.raises(HTTPException) as exc:
            await activate_by_stable_id(
                stable_id="SID",
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc.value.detail == (
        "평가기준 변경 중 오류가 발생했습니다: ConnectError"
    )
    assert "복구 전 rollback 실패: IntegrityError" in caplog.text
    assert "DB 캐시 복구 실패: IntegrityError" in caplog.text
    assert _MARKER not in caplog.text
