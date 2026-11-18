"""File Search 업로드 작업 폴링 (#373)

업로드 응답 이후 같은 operation을 GET으로만 다시 조회한다. 시작할 때 정한 실제
시간 마감 안에서 일시 오류(#368 판정)만 operation 전체에 최대 2번 더 시도한다.
업로드 자체는 다시 보내지 않는다(멱등 키가 없어 중복 등록될 수 있다).
"""

import asyncio
import logging

from app.config import settings
from app.utils.gemini_retry import _is_connection_error, _is_retryable

logger = logging.getLogger(__name__)

_RETRY_WAITS = (2.0, 4.0)  # 추가 GET 앞의 대기(초)

_sleep = asyncio.sleep  # 테스트가 가짜 시계로 바꾼다


def _now() -> float:
    return asyncio.get_running_loop().time()


async def poll_operation(client, operation, *, deadline_s, interval_s, label):
    """operation이 끝날 때까지 조회하고, 성공한 operation을 돌려준다.

    마감이 지나면 TimeoutError, done.error면 RuntimeError. 소진되었거나
    재시도 대상이 아닌 GET 오류는 원인 그대로 올리되, timeout이 아닌 연결
    오류는 메시지 없는 RuntimeError로 감싼다.
    """
    deadline = _now() + deadline_s
    retry_waits = list(_RETRY_WAITS)

    def remaining() -> float:
        return deadline - _now()

    def expired():
        return TimeoutError(
            f"{label}: 작업 폴링 타임아웃 ({deadline_s}초 초과)"
        )

    wait = interval_s
    while not operation.done:
        await _sleep(max(0.0, min(wait, remaining())))
        left = remaining()
        if left * 1000 < 1:
            raise expired()
        timeout_ms = int(min(settings.GEMINI_HTTP_TIMEOUT_MS, left * 1000))
        try:
            operation = await asyncio.wait_for(
                client.aio.operations.get(
                    operation, config={"http_options": {"timeout": timeout_ms}}
                ),
                timeout=left,
            )
        except TimeoutError as e:  # wait_for가 남은 시간에서 끊었다
            raise expired() from e
        except Exception as e:
            if remaining() <= 0:
                raise expired() from e
            if not _is_retryable(e) or not retry_waits:
                if _is_connection_error(e):
                    # h11은 응답 헤더 줄을 메시지에 넣고 호출부는 str(e)를
                    # 응답·DB에 남기므로 원문 없이 올린다 (원인은 __cause__)
                    raise RuntimeError(
                        f"{label}: 작업 상태 조회 연결 오류 ({type(e).__name__})"
                    ) from e
                raise
            wait = retry_waits.pop(0)
            logger.warning(
                "%s: 작업 조회 일시 오류(%s), %.0f초 뒤 다시 조회",
                label,
                type(e).__name__,
                wait,
            )
            continue
        wait = interval_s

    if operation.error:
        raise RuntimeError(f"{label}: 작업 실패: {operation.error}")
    if not getattr(operation.response, "document_name", None):
        raise RuntimeError(f"{label}: 작업 응답에 document_name이 없다")
    return operation
