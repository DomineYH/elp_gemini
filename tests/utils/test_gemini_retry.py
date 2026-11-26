from unittest.mock import MagicMock

import httpx
import pytest
from google.genai import errors as genai_errors

from app.utils.gemini_retry import (
    GeminiQuotaExhausted,
    GeminiServerOverloaded,
    retry_on_resource_exhausted,
)


def _make_429():
    # google-genai ClientError signature: (code, response_json, response)
    return genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Failed to embed content.",
                "status": "RESOURCE_EXHAUSTED",
            }
        },
        MagicMock(),
    )


def _make_503():
    # google-genai ServerError signature: (code, response_json, response)
    return genai_errors.ServerError(
        503,
        {
            "error": {
                "code": 503,
                "message": "high demand.",
                "status": "UNAVAILABLE",
            }
        },
        MagicMock(),
    )


def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    @retry_on_resource_exhausted(max_attempts=3, initial_wait=0.0)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _make_429()
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_raises_gemini_quota_exhausted_after_max_attempts():
    @retry_on_resource_exhausted(max_attempts=2, initial_wait=0.0)
    def always_429():
        raise _make_429()

    with pytest.raises(GeminiQuotaExhausted):
        always_429()


def test_passes_through_non_429_errors():
    @retry_on_resource_exhausted(max_attempts=3, initial_wait=0.0)
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        boom()


def test_retries_on_503_then_succeeds():
    """전이성 503(모델 과부하)도 백오프 재시도 후 성공해야 한다 (#120)."""
    calls = {"n": 0}

    @retry_on_resource_exhausted(max_attempts=3, initial_wait=0.0)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _make_503()
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_raises_gemini_server_overloaded_after_max_attempts():
    """503 재시도 소진 시 GeminiServerOverloaded 로 변환된다 (#120)."""

    @retry_on_resource_exhausted(max_attempts=2, initial_wait=0.0)
    def always_503():
        raise _make_503()

    with pytest.raises(GeminiServerOverloaded):
        always_503()


def test_retries_on_transport_error_then_succeeds():
    """끊긴 연결(RemoteProtocolError)도 재시도한다 (#368)."""
    calls = {"n": 0}

    @retry_on_resource_exhausted(max_attempts=3, initial_wait=0.0)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.RemoteProtocolError("Server disconnected")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 2


def test_transport_error_is_reraised_after_max_attempts():
    calls = {"n": 0}

    @retry_on_resource_exhausted(max_attempts=3, initial_wait=0.0)
    def always_disconnect():
        calls["n"] += 1
        raise httpx.ConnectError("refused")

    with pytest.raises(httpx.ConnectError):
        always_disconnect()
    assert calls["n"] == 3


def test_timeout_is_not_retried():
    """timeout은 TransportError 하위지만 재시도하지 않는다 (#368)."""
    calls = {"n": 0}

    @retry_on_resource_exhausted(max_attempts=3, initial_wait=0.0)
    def slow():
        calls["n"] += 1
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(httpx.ReadTimeout):
        slow()
    assert calls["n"] == 1


def test_timeout_is_retried_when_opted_in():
    """retry_timeouts=True 면 timeout도 다시 부르고, 소진되면 그대로 올린다 (#464)."""
    calls = {"n": 0}

    @retry_on_resource_exhausted(
        max_attempts=3, initial_wait=0.0, retry_timeouts=True
    )
    def slow():
        calls["n"] += 1
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(httpx.ReadTimeout):
        slow()
    assert calls["n"] == 3


def test_opted_in_timeout_once_then_succeeds():
    calls = {"n": 0}

    @retry_on_resource_exhausted(initial_wait=0.0, retry_timeouts=True)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("timed out")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 2
