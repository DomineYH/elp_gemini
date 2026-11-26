"""
Gemini API retry helpers.

Wraps blocking Gemini SDK calls with exponential-backoff retry on transient
failures:
- 429 RESOURCE_EXHAUSTED (ClientError) -> GeminiQuotaExhausted -> HTTP 429.
- 5xx server overload (ServerError, e.g. 503 UNAVAILABLE "high demand")
  -> GeminiServerOverloaded -> HTTP 503.
- Connection errors (httpx.TransportError except timeouts, e.g. a dropped
  keep-alive RemoteProtocolError) -> re-raised as-is when exhausted (#368).

After max attempts, raises the mapped exception so the caller can return a
friendly "busy, retry later" response instead of a generic 500 (issue #120).
"""

import functools
import logging
from typing import Callable, TypeVar

import httpx
from google.genai import errors as genai_errors
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Transient server-side status codes worth retrying. ServerError (5xx) from the
# Gen AI backend is generally transient; 503 UNAVAILABLE ("high demand") is the
# common one (issue #120).
_RETRYABLE_SERVER_CODES = {500, 502, 503, 504}


class GeminiQuotaExhausted(Exception):
    """Raised when 429 retries are exhausted."""


class GeminiServerOverloaded(Exception):
    """Raised when transient 5xx (e.g. 503) retries are exhausted."""


def _is_resource_exhausted(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.ClientError):
        return getattr(exc, "code", None) == 429
    return False


def _is_server_overloaded(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.ServerError):
        return getattr(exc, "code", None) in _RETRYABLE_SERVER_CODES
    return False


def _is_connection_error(exc: BaseException) -> bool:
    # timeout은 이미 오래 기다린 뒤라 재시도하지 않는다 (#368)
    return isinstance(exc, httpx.TransportError) and not isinstance(
        exc, httpx.TimeoutException
    )


def _is_retryable(exc: BaseException) -> bool:
    return (
        _is_resource_exhausted(exc)
        or _is_server_overloaded(exc)
        or _is_connection_error(exc)
    )


def is_transient_lookup_error(exc: BaseException) -> bool:
    """조회 실패가 일시 오류인지: 재시도 대상, 시간 초과, 모든 5xx, 재시도 소진 뒤의 변환 예외 (#465)."""
    return _is_retryable(exc) or isinstance(
        exc,
        (
            httpx.TimeoutException,
            genai_errors.ServerError,
            GeminiQuotaExhausted,
            GeminiServerOverloaded,
        ),
    )


def retry_on_resource_exhausted(
    max_attempts: int = 3,
    initial_wait: float = 2.0,
    max_wait: float = 16.0,
    *,
    retry_timeouts: bool = False,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator: retry the wrapped sync callable on transient Gemini errors
    (429 RESOURCE_EXHAUSTED, 5xx server overload or a non-timeout connection
    error) with exponential backoff
    (initial_wait, 2x, 4x ... capped at max_wait).
    """

    def should_retry(exc: BaseException) -> bool:
        # 요청별 제한이 짧은 조회(GET)만 timeout도 다시 부른다 (#464)
        return _is_retryable(exc) or (
            retry_timeouts and isinstance(exc, httpx.TimeoutException)
        )

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            tenacity_retry = retry(
                retry=retry_if_exception(should_retry),
                stop=stop_after_attempt(max_attempts),
                wait=(
                    wait_exponential(multiplier=initial_wait, max=max_wait)
                    if initial_wait > 0
                    else wait_exponential(multiplier=0, max=0)
                ),
                reraise=True,
            )
            try:
                return tenacity_retry(fn)(*args, **kwargs)
            except genai_errors.ClientError as e:
                if _is_resource_exhausted(e):
                    logger.error(
                        "Gemini 429 RESOURCE_EXHAUSTED after %d attempts: %s",
                        max_attempts,
                        e,
                    )
                    raise GeminiQuotaExhausted(str(e)) from e
                raise
            except genai_errors.ServerError as e:
                if _is_server_overloaded(e):
                    logger.error(
                        "Gemini 5xx server overload after %d attempts: %s",
                        max_attempts,
                        e,
                    )
                    raise GeminiServerOverloaded(str(e)) from e
                raise

        return wrapper

    return decorator
