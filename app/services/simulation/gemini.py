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
        http_options={"api_version": "v1beta"},
    )


def parse_structured(schema: type[BaseModel], text: str | None):
    """깨진 JSON·스키마 불일치 → None."""
    try:
        return schema.model_validate_json(text or "")
    except ValidationError:
        return None


def _warn_rejected(kind, persona_key, schema, text: str) -> None:
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
        "simulation %s output rejected (persona_key=%s, len=%d): %s",
        kind,
        persona_key,
        len(text),
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

    # ponytail: SDK 기본 타임아웃만 쓴다.
    # 느린 응답이 문제 되면 http_options에 timeout 추가.
    @retry_on_resource_exhausted(
        max_attempts=3, initial_wait=2.0, max_wait=16.0
    )
    def _generate():
        return _client().models.generate_content(
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
            _warn_rejected(kind, persona_key, schema, text)
    return LLMResult(
        parsed=parsed,
        text=text,
        model=model,
        temperature=TEMPERATURE,
        latency_ms=latency_ms,
    )


async def call_many(calls: list[dict]) -> list[LLMResult]:
    """call_structured 여러 개를 병렬로. 오류 정책(PLAN 2.3):

    하나라도 한도 초과 → RESOURCE_EXHAUSTED, 아니면 과부하 → MODEL_OVERLOADED.
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
    if errors:
        raise errors[0]
    return results
