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

from app.routers.auth import logout

USER_ID = 247


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
        patch("app.services.file_search_service.FileSearchService") as fss,
    ):
        yield forget, fss.return_value


@pytest.mark.asyncio
async def test_logout_returns_before_store_delete(patched):
    forget, service = patched
    release = asyncio.Event()

    async def slow_delete(_name):
        await release.wait()

    service.delete_store_by_display_name = AsyncMock(side_effect=slow_delete)
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
    service.delete_store_by_display_name.assert_not_awaited()

    release.set()
    await asyncio.wait_for(tasks(), timeout=1)
    service.delete_store_by_display_name.assert_awaited_once_with(
        f"user-{USER_ID}-store"
    )


@pytest.mark.asyncio
async def test_background_delete_failure_only_warns(patched, caplog):
    _, service = patched
    service.delete_store_by_display_name = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    tasks = BackgroundTasks()

    res = await logout(_request(), tasks, db=MagicMock())
    with caplog.at_level("WARNING", logger="app.routers.auth"):
        await tasks()

    assert res.status_code == 302
    assert "로그아웃 시 스토어 정리 실패: boom" in caplog.text
