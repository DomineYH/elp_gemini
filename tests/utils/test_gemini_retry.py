import pytest
from unittest.mock import MagicMock
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
        {"error": {"code": 429, "message": "Failed to embed content.",
                   "status": "RESOURCE_EXHAUSTED"}},
        MagicMock(),
    )


def _make_503():
    # google-genai ServerError signature: (code, response_json, response)
    return genai_errors.ServerError(
        503,
        {"error": {"code": 503, "message": "high demand.",
                   "status": "UNAVAILABLE"}},
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
