"""업로드 작업 폴링: 실제 시간 마감과 같은 operation GET 재시도 (#373)

가짜 SDK와 가짜 시계로 세 진입점을 같은 시나리오로 확인한다.
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from google.genai import errors as genai_errors

from app.config import settings
from app.schemas.alias_map import AliasMap
from app.services import operation_polling
from app.services.criteria_alias_map_service import CriteriaAliasMapService
from app.services.file_search_service import FileSearchService

# 진입점별 (마감 초, 정상 조회 간격 초)
BUDGETS = {"upload": (300, 5), "alias": (60, 2), "manifest": (30, 1)}


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def _op(name="operations/up-1", done=False, error=None, doc="docs/new"):
    op = Mock()
    op.name = name
    op.done = done
    op.error = error
    op.response = (
        SimpleNamespace(document_name=doc, parent="fileSearchStores/s")
        if done and not error
        else None
    )
    return op


def _pending():
    return _op(done=False)


def _done():
    return _op(done=True)


def _api_error(code):
    cls = genai_errors.ServerError if code >= 500 else genai_errors.ClientError
    return cls(code, {"error": {"code": code, "message": f"e{code}"}}, None)


def _client(first_op, get_side_effect):
    client = Mock()
    store = Mock(display_name="rubric-store")
    store.name = "fileSearchStores/s"
    client.file_search_stores.list = Mock(return_value=[store])
    client.file_search_stores.documents.list = Mock(return_value=[])
    client.file_search_stores.documents.delete = Mock()
    client.file_search_stores.upload_to_file_search_store = Mock(
        return_value=first_op
    )
    client.aio.operations.get = AsyncMock(side_effect=get_side_effect)
    return client


async def _run(entry, client, tmp_path):
    if entry == "alias":
        alias_map = AliasMap(
            schema_version=1, updated_at="2026-11-18T00:00:00Z", entries={}
        )
        return await CriteriaAliasMapService(client, "rubric-store").replace(
            alias_map, "docs/alias-old"
        )
    svc = FileSearchService.__new__(FileSearchService)
    svc.client = client
    svc.main_store_name = "main"
    svc.rubric_store_name = "rubric"
    svc._get_or_create_store = Mock(
        return_value=client.file_search_stores.list.return_value[0]
    )
    if entry == "upload":
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF")
        return await svc.upload_document(str(pdf), "a.pdf", {"user_id": "1"})
    return await svc.replace_single_document(
        "fileSearchStores/s", "manifest.json", b"{}"
    )


@pytest.fixture
def clock():
    c = FakeClock()
    with (
        patch.object(operation_polling, "_now", c.now),
        patch.object(operation_polling, "_sleep", c.sleep),
    ):
        yield c


@pytest.fixture(autouse=True)
def _budgets():
    with (
        patch.object(settings, "FS_UPLOAD_TIMEOUT", 300),
        patch.object(settings, "FS_POLL_INTERVAL", 5),
    ):
        yield


ENTRIES = ["upload", "alias", "manifest"]


def _gets(client):
    return client.aio.operations.get.await_args_list


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
async def test_immediately_done_makes_no_get(entry, clock, tmp_path):
    client = _client(_done(), [])

    await _run(entry, client, tmp_path)

    assert _gets(client) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
async def test_pending_then_503_then_done(entry, clock, tmp_path):
    first = _pending()
    client = _client(first, [_api_error(503), _done()])

    result = await _run(entry, client, tmp_path)

    calls = _gets(client)
    assert len(calls) == 2
    assert all(c.args[0].name == first.name for c in calls)
    upload = client.file_search_stores.upload_to_file_search_store
    assert upload.call_count == 1
    assert clock.sleeps == [BUDGETS[entry][1], 2]
    doc = result["document_id"] if entry == "upload" else result
    assert doc == "docs/new"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
async def test_extra_gets_capped_at_two_and_last_cause_raised(
    entry, clock, tmp_path
):
    last = _api_error(503)
    client = _client(
        _pending(),
        [
            _api_error(429),
            _pending(),
            httpx.ConnectError("reset"),
            _pending(),
            last,
            _done(),
        ],
    )

    with pytest.raises(genai_errors.ServerError) as exc_info:
        await _run(entry, client, tmp_path)

    assert exc_info.value is last
    assert len(_gets(client)) == 5
    interval = BUDGETS[entry][1]
    assert clock.sleeps == [interval, 2, interval, 4, interval]
    client.file_search_stores.documents.delete.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize(
    "error",
    [_api_error(403), httpx.ReadTimeout("slow")],
    ids=["403", "ReadTimeout"],
)
async def test_non_retryable_error_gets_once(entry, error, clock, tmp_path):
    client = _client(_pending(), [error, _done()])

    with pytest.raises(type(error)):
        await _run(entry, client, tmp_path)

    assert len(_gets(client)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
async def test_done_error_is_failure(entry, clock, tmp_path):
    failed = _op(done=True, error={"code": 13, "message": "indexing failed"})
    client = _client(_pending(), [failed])

    with pytest.raises(RuntimeError, match="indexing failed"):
        await _run(entry, client, tmp_path)

    client.file_search_stores.documents.delete.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
async def test_done_without_document_name_is_failure(entry, clock, tmp_path):
    client = _client(_pending(), [_op(done=True, doc=None)])

    with pytest.raises(RuntimeError):
        await _run(entry, client, tmp_path)

    client.file_search_stores.documents.delete.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
async def test_deadline_during_backoff_stops_without_more_gets(
    entry, clock, tmp_path
):
    deadline, _ = BUDGETS[entry]

    async def get(op, config=None):
        # 마감 1초 전에 503: 2초 백오프 도중 마감이 온다
        clock.t = start + deadline - 1
        raise _api_error(503)

    client = _client(_pending(), None)
    client.aio.operations.get = AsyncMock(side_effect=get)
    start = clock.t

    with pytest.raises(TimeoutError):
        await _run(entry, client, tmp_path)

    assert len(_gets(client)) == 1
    assert clock.t - start == pytest.approx(deadline)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
async def test_hung_last_get_stops_at_deadline(entry, clock, tmp_path):
    deadline, interval = BUDGETS[entry]
    seen = []

    async def get(op, config=None):
        seen.append((config["http_options"]["timeout"], clock.t))
        if len(seen) == 1:
            # 다음 조회가 마감 50ms 전에 오도록 시계를 옮긴다
            clock.t = start + deadline - interval - 0.05
            return _pending()
        await asyncio.Event().wait()  # 멈춘 GET

    client = _client(_pending(), None)
    client.aio.operations.get = AsyncMock(side_effect=get)
    start = clock.t
    real_start = time.monotonic()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(_run(entry, client, tmp_path), timeout=5)

    assert time.monotonic() - real_start < 1  # 바깥 5초 가드가 아니다
    assert len(seen) == 2
    timeout_ms, at = seen[-1]
    assert 0 < timeout_ms <= (start + deadline - at) * 1000
    assert timeout_ms <= settings.GEMINI_HTTP_TIMEOUT_MS


@pytest.mark.asyncio
async def test_request_timeout_is_capped_by_remaining_time(clock, tmp_path):
    seen = []

    async def get(op, config=None):
        seen.append((config["http_options"]["timeout"], clock.t))
        return _pending()

    client = _client(_pending(), None)
    client.aio.operations.get = AsyncMock(side_effect=get)
    start = clock.t

    with pytest.raises(TimeoutError):
        await _run("manifest", client, tmp_path)

    assert seen
    for timeout_ms, at in seen:
        assert 0 < timeout_ms <= (start + 30 - at) * 1000
    assert clock.t - start == pytest.approx(30)


@pytest.mark.asyncio
async def test_caller_cancel_propagates(clock, tmp_path):
    started = asyncio.Event()

    async def get(op, config=None):
        started.set()
        await asyncio.Event().wait()

    client = _client(_pending(), None)
    client.aio.operations.get = AsyncMock(side_effect=get)
    task = asyncio.create_task(_run("alias", client, tmp_path))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    client.file_search_stores.documents.delete.assert_not_called()


MARKER = "x-goog-api-key: SECRET-MARKER"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
async def test_retry_warning_has_no_error_message(
    entry, clock, tmp_path, caplog
):
    # h11은 잘못된 응답 헤더 줄 전체를 메시지에 넣는다
    client = _client(_pending(), [httpx.RemoteProtocolError(MARKER), _done()])

    with caplog.at_level("WARNING", logger=operation_polling.logger.name):
        await _run(entry, client, tmp_path)

    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.name == operation_polling.logger.name
    ]
    assert len(warnings) == 1
    assert "RemoteProtocolError" in warnings[0]
    assert "SECRET-MARKER" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES)
async def test_exhausted_connection_error_hides_message(
    entry, clock, tmp_path, caplog
):
    last = httpx.RemoteProtocolError(MARKER)
    client = _client(
        _pending(),
        [
            httpx.RemoteProtocolError(MARKER),
            httpx.RemoteProtocolError(MARKER),
            last,
        ],
    )

    with pytest.raises(RuntimeError) as exc_info:
        await _run(entry, client, tmp_path)

    assert "SECRET-MARKER" not in str(exc_info.value)
    assert "RemoteProtocolError" in str(exc_info.value)
    assert exc_info.value.__cause__ is last
    assert len(_gets(client)) == 3
    assert "SECRET-MARKER" not in caplog.text
