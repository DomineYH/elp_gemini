"""
로그아웃이 클라우드 스토어 삭제를 기다리지 않는다 (#247)

ASGITransport/TestClient는 백그라운드 작업까지 기다린 뒤 응답을
돌려주므로, 핸들러를 직접 호출해 응답과 삭제를 따로 관찰한다.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks
from fastapi.responses import RedirectResponse
from starlette.requests import Request

from app.routers.auth import _delete_user_stores, logout

USER_ID = 247
STORE_ID = "fileSearchStores/user247store-abc"
OTHER_STORE_ID = "fileSearchStores/user247store-def"


def _request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/logout",
        "headers": [],
        "session": {"user_id": USER_ID, "username": "t247"},
    }
    return Request(scope)


@pytest.fixture
def patched():
    """세션 무효화·DB 정리·스토어 삭제를 모두 목으로 바꾼다."""
    with (
        patch(
            "app.routers.auth.AuthService.revoke_sessions_if_current",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.services.simulation.lessonplan_source."
            "forget_file_search_ids",
            new=AsyncMock(),
        ) as forget,
        # 비우기 전에 읽은 업로드 행의 스토어 id (#470)
        patch(
            "app.services.simulation.lessonplan_source.get_store_ids",
            new=AsyncMock(return_value=[STORE_ID]),
        ),
        patch("app.services.file_search_service.FileSearchService") as fss,
    ):
        yield forget, fss.return_value


@pytest.mark.asyncio
async def test_logout_returns_before_store_delete(patched):
    forget, service = patched
    release = asyncio.Event()

    async def slow_delete(_name):
        await release.wait()

    service.delete_store = AsyncMock(side_effect=slow_delete)
    request = _request()
    tasks = BackgroundTasks()

    res = await asyncio.wait_for(
        logout(request, tasks, db=MagicMock()), timeout=1
    )

    assert isinstance(res, RedirectResponse)
    assert res.status_code == 302
    assert res.headers["location"] == "/login"
    assert request.session == {}
    # 지워진 문서의 QnA 버튼이 남지 않도록 DB 정리는 요청 안에서 끝난다 (#173)
    forget.assert_awaited_once()
    service.delete_store.assert_not_awaited()

    release.set()
    await asyncio.wait_for(tasks(), timeout=1)
    service.delete_store.assert_awaited_once_with(STORE_ID)


@pytest.mark.asyncio
async def test_background_delete_failure_only_warns(patched, caplog):
    _, service = patched
    service.delete_store = AsyncMock(side_effect=RuntimeError("boom"))
    tasks = BackgroundTasks()

    res = await logout(_request(), tasks, db=MagicMock())
    with caplog.at_level("WARNING", logger="app.routers.auth"):
        await tasks()

    assert res.status_code == 302
    assert (
        f"로그아웃 시 스토어 정리 실패: user_id={USER_ID}, RuntimeError"
        in caplog.text
    )
    assert "boom" not in caplog.text


@pytest.mark.asyncio
async def test_forget_ids_failure_logs_type_only(patched, caplog):
    # DB 오류 원문에는 쿼리나 값이 섞일 수 있어 종류만 남긴다 (#466)
    forget, _ = patched
    forget.side_effect = RuntimeError("sensitive-marker")

    with caplog.at_level("WARNING", logger="app.routers.auth"):
        res = await logout(_request(), BackgroundTasks(), db=MagicMock())

    assert res.status_code == 302
    assert "로그아웃 시 스토어 정리 실패" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "sensitive-marker" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failing",
    [[STORE_ID], [STORE_ID, OTHER_STORE_ID]],
    ids=["첫 스토어만 실패", "둘 다 실패"],
)
async def test_delete_tries_every_store_and_logs_only_failed_ids(
    caplog, failing
):
    # 행의 id 는 이미 비웠다. 남은 스토어는 이 로그의 id 로만 찾는다 (#486)
    calls = []

    async def delete_store(store_id):
        calls.append(store_id)
        if store_id in failing:
            raise RuntimeError("boom")

    with (
        patch("app.services.file_search_service.FileSearchService") as fss,
        caplog.at_level("WARNING", logger="app.routers.auth"),
    ):
        fss.return_value.delete_store = delete_store
        await _delete_user_stores(USER_ID, [STORE_ID, OTHER_STORE_ID])

    assert calls == [STORE_ID, OTHER_STORE_ID]
    logged = [r.getMessage() for r in caplog.records]
    assert len(logged) == len(failing)
    for store_id, message in zip(failing, logged):
        assert message == (
            f"로그아웃 시 스토어 정리 실패: user_id={USER_ID}, "
            f"RuntimeError, store={store_id}"
        )


@pytest.mark.asyncio
async def test_service_construction_failure_logs_every_store(caplog):
    with (
        patch(
            "app.services.file_search_service.FileSearchService",
            side_effect=ValueError("sensitive-marker"),
        ),
        caplog.at_level("WARNING", logger="app.routers.auth"),
    ):
        await _delete_user_stores(USER_ID, [STORE_ID, OTHER_STORE_ID])

    assert "ValueError" in caplog.text
    assert STORE_ID in caplog.text
    assert OTHER_STORE_ID in caplog.text
    assert "sensitive-marker" not in caplog.text
