"""
시뮬레이션의 유일한 Gemini 호출 지점 (PLAN 2.3).

호출부는 `from app.services.simulation import gemini` 후
`gemini.call_structured(...)`로 부른다(테스트가 이 함수 하나만 바꾼다).
"""

import asyncio
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.services.simulation.errors import SimulationError
from app.utils.gemini_retry import (
    GeminiQuotaExhausted,
    GeminiServerOverloaded,
    retry_on_resource_exhausted,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

Kind = Literal["phase_split", "adapt", "student", "feedback"]
TEMPERATURE = 1.0


@dataclass(frozen=True)
class LLMResult:
    parsed: BaseModel | None
    text: str
    model: str
    temperature: float
    latency_ms: int


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(
        api_key=settings.GOOGLE_API_KEY,
        http_options=types.HttpOptions(
            api_version="v1beta",
            timeout=settings.GEMINI_HTTP_TIMEOUT_MS,
        ),
    )


def parse_structured(schema: type[BaseModel], text: str | None):
    """깨진 JSON·스키마 불일치 → None."""
    try:
        return schema.model_validate_json(text or "")
    except ValidationError:
        return None


def _reason(response) -> str:
    """빈·잘린 응답의 사유. enum 이름과 후보 수만 남긴다(원문·프롬프트·finish_message 제외) (#409)."""
    candidates = getattr(response, "candidates", None) or []
    block = getattr(
        getattr(response, "prompt_feedback", None), "block_reason", None
    )
    finish = (
        getattr(candidates[0], "finish_reason", None) if candidates else None
    )
    return "block_reason=%s, finish_reason=%s, candidates=%d" % (
        getattr(block, "name", block),
        getattr(finish, "name", finish),
        len(candidates),
    )


def _warn_rejected(kind, persona_key, schema, text: str, reason: str) -> None:
    """spec_dev 8: 필드 경로·메시지·길이만 남긴다(원문·프롬프트 제외)."""
    try:
        schema.model_validate_json(text)
        return
    except ValidationError as e:
        errors = "; ".join(
            f"{'.'.join(map(str, err['loc'])) or '<root>'}: {err['msg']}"
            for err in e.errors(include_input=False, include_url=False)
        )
    logger.warning(
        "simulation %s output rejected (persona_key=%s, len=%d, %s): %s",
        kind,
        persona_key,
        len(text),
        reason,
        errors,
    )


def call_structured(
    kind: Kind,
    *,
    system: str,
    user: str,
    schema: type[BaseModel],
    persona_key: str | None = None,
) -> LLMResult:
    """kind·persona_key는 가짜 픽스처와 로그용.

    GeminiQuotaExhausted / GeminiServerOverloaded는 그대로 올린다.
    """
    model = settings.GEMINI_SIM_MODEL

    @retry_on_resource_exhausted(
        max_attempts=3, initial_wait=2.0, max_wait=16.0
    )
    def _generate():
        # 첫 호출 lru_cache 경합의 미캐시 Client가 호출 중 닫히지 않게 참조를 잡아 둔다 (#275)
        client = _client()
        return client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=TEMPERATURE,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )

    started = time.perf_counter()
    response = _generate()
    latency_ms = int((time.perf_counter() - started) * 1000)
    text = response.text or ""
    parsed = response.parsed
    if not isinstance(parsed, schema):
        parsed = parse_structured(schema, text)
        if parsed is None:
            _warn_rejected(kind, persona_key, schema, text, _reason(response))
    return LLMResult(
        parsed=parsed,
        text=text,
        model=model,
        temperature=TEMPERATURE,
        latency_ms=latency_ms,
    )


async def call_many(calls: list[dict]) -> list[LLMResult]:
    """call_structured 여러 개를 병렬로. 오류 정책(PLAN 2.3):

    하나라도 한도 초과 → RESOURCE_EXHAUSTED, 아니면 과부하 → MODEL_OVERLOADED,
    아니면 timeout → MODEL_TIMEOUT, 그 밖의 전송 오류 → MODEL_UNAVAILABLE.
    """
    results = await asyncio.gather(
        *(asyncio.to_thread(call_structured, **kw) for kw in calls),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, BaseException)]
    if any(isinstance(e, GeminiQuotaExhausted) for e in errors):
        raise SimulationError("RESOURCE_EXHAUSTED")
    if any(isinstance(e, GeminiServerOverloaded) for e in errors):
        raise SimulationError("MODEL_OVERLOADED")
    timeouts = [e for e in errors if isinstance(e, httpx.TimeoutException)]
    # TimeoutException 도 TransportError 하위라 timeout을 먼저 고른다
    transport = [e for e in errors if isinstance(e, httpx.TransportError)]
    if transport:
        e = (timeouts or transport)[0]
        # str(e) can carry raw response header lines (h11), so log the class only
        logger.warning(
            "simulation call_many %s (failed %d/%d)",
            type(e).__name__,
            len(errors),
            len(calls),
        )
        raise SimulationError(
            "MODEL_TIMEOUT" if timeouts else "MODEL_UNAVAILABLE"
        )
    if errors:
        raise errors[0]
    return results
