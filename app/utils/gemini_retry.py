"""
Gemini API retry helpers.

Wraps blocking Gemini SDK calls with exponential-backoff retry on
429 RESOURCE_EXHAUSTED. After max attempts, raises GeminiQuotaExhausted
so the caller can map it to HTTP 429 (instead of a generic 500).
"""
import functools
import logging
from typing import Callable, TypeVar

from google.genai import errors as genai_errors
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    RetryError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class GeminiQuotaExhausted(Exception):
    """Raised when 429 retries are exhausted."""


def _is_resource_exhausted(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.ClientError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        return code == 429
    return False


def retry_on_resource_exhausted(
    max_attempts: int = 3,
    initial_wait: float = 2.0,
    max_wait: float = 16.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator: retry the wrapped sync callable on Gemini 429 with
    exponential backoff (initial_wait, 2x, 4x ... capped at max_wait).
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            tenacity_retry = retry(
                retry=retry_if_exception(_is_resource_exhausted),
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(
                    multiplier=initial_wait, max=max_wait
                ) if initial_wait > 0 else wait_exponential(multiplier=0, max=0),
                reraise=True,
            )
            try:
                return tenacity_retry(fn)(*args, **kwargs)
            except genai_errors.ClientError as e:
                if _is_resource_exhausted(e):
                    logger.error(
                        "Gemini 429 RESOURCE_EXHAUSTED after %d attempts: %s",
                        max_attempts, e,
                    )
                    raise GeminiQuotaExhausted(str(e)) from e
                raise
            except RetryError as e:  # safety: should not happen with reraise=True
                raise GeminiQuotaExhausted(str(e)) from e
        return wrapper
    return decorator
