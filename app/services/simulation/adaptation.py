"""
번안: 원본 프로필 → 한국 초등 맥락의 관찰 가능한 행동 서술 (병렬)
"""

import json

from app.services.prompt_loader_service import PromptLoaderService
from app.services.simulation import gemini
from app.services.simulation.errors import SimulationError
from app.services.simulation.llm_schemas import AdaptationResult
from app.services.simulation.persona_pool import LEVEL_LABELS, normalize_level


async def adapt_many(
    items: list[tuple[str | None, dict]],
) -> list[tuple[dict, str]]:
    """(persona_key, raw_profile) 목록 → (adapted_profile, adapted_level) 목록.

    학업 수준(번안)은 모델에 묻지 않고 코드로 정한다.
    하나라도 파싱 실패 → ADAPT_FAILED.
    """
    system = PromptLoaderService().get_prompt("sim_adapt")
    results = await gemini.call_many(
        [
            {
                "kind": "adapt",
                "system": system,
                "user": json.dumps(raw, ensure_ascii=False),
                "schema": AdaptationResult,
                "persona_key": key,
            }
            for key, raw in items
        ]
    )
    if any(r.parsed is None for r in results):
        raise SimulationError("ADAPT_FAILED")
    adapted = []
    for (_, raw), result in zip(items, results):
        level = LEVEL_LABELS[normalize_level(raw["academic_level"])]
        adapted.append(
            ({**result.parsed.model_dump(), "adapted_level": level}, level)
        )
    return adapted
