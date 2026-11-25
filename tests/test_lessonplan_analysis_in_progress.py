"""#442: 사용자별 '분석 중' 표시와 GET /api/lessonplan/analyze/status"""

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.users import User
from app.routers import lessonplan_analysis as router_mod

SERVICE = "app.routers.lessonplan_analysis.LessonPlanAnalysisService"
SUCCESS = {"success": True, "report": "# 보고서", "latency_ms": 1}
ANALYZE = "/api/lessonplan/analyze"
STATUS = "/api/lessonplan/analyze/status"


class HeldAnalysis:
    """release 전까지 끝나지 않는 서비스 대역 (모델 호출 수 = calls)"""

    def __init__(self, result=None):
        self.result = SUCCESS if result is None else result
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, **kwargs):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.result


def _clear_markers():
    # 실패한 테스트가 남긴 표시가 다음 테스트로 번지지 않게 한다
    getattr(router_mod, "_analyzing_user_ids", set()).clear()


@pytest_asyncio.fixture
async def ctx():
    """현재 사용자를 바꿀 수 있는 테스트 클라이언트 (DB는 AsyncMock)"""
    state = {
        "user": User(id=1, username="tester", hashed_password="x"),
        "db": AsyncMock(),
    }

    async def override_get_user():
        return state["user"]

    async def override_get_db():
        yield state["db"]

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db
    _clear_markers()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        state["client"] = c
        yield state

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    _clear_markers()


def _post(client):
    return client.post(ANALYZE, json={"session_id": 1})


async def _post_now(client):
    # 분석 중의 요청은 서비스에 들어가지 않고 바로 답해야 한다 (들어가면 여기서 시간 초과)
    return await asyncio.wait_for(_post(client), 2)


async def _in_progress(client):
    res = await client.get(STATUS)
    assert res.status_code == 200
    return res.json()


@asynccontextmanager
async def _held_analysis(client, posts=1):
    """서비스에 멈춰 있는 분석 요청. 블록이 실패해도 풀어 주고 끝까지 기다린다."""
    held = HeldAnalysis()
    with patch(SERVICE) as mock_service:
        mock_service.return_value.analyze_lesson_plan = held
        held.tasks = [asyncio.create_task(_post(client)) for _ in range(posts)]
        try:
            await asyncio.wait_for(held.started.wait(), 5)
            yield held
        finally:
            held.release.set()
            await asyncio.wait(held.tasks, timeout=5)


async def test_status_is_false_when_idle(ctx):
    assert await _in_progress(ctx["client"]) == {"in_progress": False}


async def test_status_requires_login(ctx):
    app.dependency_overrides.pop(get_current_user, None)

    res = await ctx["client"].get(STATUS)

    assert res.status_code == 401


async def test_status_is_true_only_for_the_analyzing_user(ctx):
    client = ctx["client"]
    async with _held_analysis(client) as held:
        assert await _in_progress(client) == {"in_progress": True}
        assert router_mod.is_analysis_in_progress(1) is True

        ctx["user"] = User(id=2, username="other", hashed_password="x")
        assert await _in_progress(client) == {"in_progress": False}
        assert router_mod.is_analysis_in_progress(2) is False
        ctx["user"] = User(id=1, username="tester", hashed_password="x")

    assert held.tasks[0].result().status_code == 200
    assert await _in_progress(client) == {"in_progress": False}


async def test_post_while_in_progress_is_409_without_model_call(ctx):
    client = ctx["client"]
    async with _held_analysis(client) as held:
        second = await _post_now(client)

        assert second.status_code == 409
        body = second.json()
        assert body["error_code"] == "ANALYSIS_IN_PROGRESS"
        assert body["detail"]
        assert "report_id" not in body
        assert "x-report-id" not in second.headers
        assert held.calls == 1
        # 거절된 요청이 앞 요청의 표시를 지우면 안 된다
        assert await _in_progress(client) == {"in_progress": True}

    assert held.tasks[0].result().status_code == 200
    assert held.calls == 1


async def test_two_simultaneous_posts_reach_the_service_once(ctx):
    async with _held_analysis(ctx["client"], posts=2) as held:
        done, _ = await asyncio.wait(
            held.tasks, return_when=asyncio.FIRST_COMPLETED, timeout=1
        )
        assert [task.result().status_code for task in done] == [409]

    assert sorted(t.result().status_code for t in held.tasks) == [200, 409]
    assert held.calls == 1


@pytest.mark.parametrize(
    "result, expected_status",
    [
        (SUCCESS, 200),
        (
            {
                "success": False,
                "error": "이미 분석된 문서입니다.",
                "error_code": "ALREADY_ANALYZED",
                "report_id": 17,
            },
            409,
        ),
        (
            {
                "success": False,
                "error": "x",
                "error_code": "RESOURCE_EXHAUSTED",
            },
            429,
        ),
        (
            {"success": False, "error": "x", "error_code": "MODEL_OVERLOADED"},
            503,
        ),
        ({"success": False, "error": "분석 시간 초과 (180초)"}, 500),
        # #439가 더하는 결과: 라우터는 일반 500 분기로 내보낸다
        ({"success": False, "error": "x", "error_code": "INVALID_REPORT"}, 500),
        (RuntimeError("boom"), 500),
    ],
    ids=["success", "already", "429", "503", "timeout", "invalid", "raise"],
)
async def test_marker_is_cleared_on_every_exit(ctx, result, expected_status):
    client = ctx["client"]
    analyze = AsyncMock(
        side_effect=result if isinstance(result, Exception) else None,
        return_value=result,
    )
    with patch(SERVICE) as mock_service:
        mock_service.return_value.analyze_lesson_plan = analyze

        res = await _post(client)
        assert res.status_code == expected_status
        assert await _in_progress(client) == {"in_progress": False}

        # 표시가 남지 않았으므로 다음 요청은 다시 서비스까지 간다
        assert (await _post(client)).status_code == expected_status
        assert analyze.await_count == 2


async def test_already_analyzed_response_is_unchanged(ctx):
    result = {
        "success": False,
        "error": "이미 분석된 문서입니다.",
        "error_code": "ALREADY_ANALYZED",
        "report_id": 17,
    }
    with patch(SERVICE) as mock_service:
        mock_service.return_value.analyze_lesson_plan = AsyncMock(
            return_value=result
        )
        res = await _post(ctx["client"])

    assert res.status_code == 409
    assert res.json() == {"detail": "이미 분석된 문서입니다.", "report_id": 17}
    assert res.headers.get("x-report-id") == "17"


async def test_marker_is_cleared_when_commit_fails(ctx):
    ctx["db"].commit.side_effect = RuntimeError("db down")
    with patch(SERVICE) as mock_service:
        mock_service.return_value.analyze_lesson_plan = AsyncMock(
            return_value=SUCCESS
        )
        res = await _post(ctx["client"])

    assert res.status_code == 500
    assert router_mod.is_analysis_in_progress(1) is False


async def test_client_disconnect_keeps_marker_until_the_handler_ends(ctx):
    """uvicorn과 같은 신호(http.disconnect)를 받아도 처리는 끝까지 간다"""
    client = ctx["client"]
    held = HeldAnalysis()
    body = json.dumps({"session_id": 1}).encode()
    gone = asyncio.Event()
    first = True

    async def receive():
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": body, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": ANALYZE,
        "raw_path": ANALYZE.encode(),
        "query_string": b"",
        "root_path": "",
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
        "headers": [
            (b"host", b"test"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "state": {},
    }

    with patch(SERVICE) as mock_service:
        mock_service.return_value.analyze_lesson_plan = held
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(held.started.wait(), 5)
            gone.set()
            await asyncio.sleep(0.05)

            assert not task.done()
            assert await _in_progress(client) == {"in_progress": True}
            assert (await _post_now(client)).status_code == 409
        finally:
            held.release.set()
            await asyncio.wait_for(task, 5)

    assert held.calls == 1
    ctx["db"].commit.assert_awaited()
    assert await _in_progress(client) == {"in_progress": False}
