"""
국면 초안: 직전 세션 승계 → 지도안 자동 분해 → 실패 시 빈 3행(도입/활동1/정리)
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.simulation_phase import SimulationPhase
from app.models.simulation_session import SimulationSession
from app.services.prompt_loader_service import PromptLoaderService
from app.services.simulation import gemini, lessonplan_source
from app.services.simulation.errors import SimulationError
from app.services.simulation.llm_schemas import PhaseSplitResult

FALLBACK_NAMES = ("도입", "활동1", "정리")
FALLBACK_NOTICE = (
    "지도안에서 국면을 찾지 못했습니다. "
    "국면 이름과 교사 발문을 직접 입력해 주세요."
)
MAX_PHASES = 8
# PhaseIn 길이 제한. 모델 출력이 넘으면 잘라서 세션 생성 422를 막는다.
FIELD_LIMITS = {
    "name": 50,
    "teacher_prompt": 2000,
    "task": 2000,
    "materials": 4000,
    "cautions": 4000,
    "source_span": 4000,
}


def fallback_phases() -> list[dict]:
    return [
        {
            "name": name,
            "minutes": None,
            "teacher_prompt": "",
            "task": "",
            "materials": "",
            "cautions": "",
            "source_span": "",
        }
        for name in FALLBACK_NAMES
    ]


def _fit(item: dict) -> dict:
    fitted = {k: item[k][:n] for k, n in FIELD_LIMITS.items()}
    minutes = item["minutes"]
    fitted["minutes"] = minutes if minutes in range(181) else None
    return fitted


async def _inherited(db: AsyncSession, upload_id: int) -> list[dict]:
    sid = await db.scalar(
        select(SimulationSession.id)
        .where(SimulationSession.upload_id == upload_id)
        .order_by(
            SimulationSession.created_at.desc(),
            SimulationSession.id.desc(),
        )
        .limit(1)
    )
    if sid is None:
        return []
    rows = await db.scalars(
        select(SimulationPhase)
        .where(SimulationPhase.session_id == sid)
        .order_by(SimulationPhase.idx)
    )
    return [
        {"minutes": r.minutes, **{k: getattr(r, k) for k in FIELD_LIMITS}}
        for r in rows
    ]


async def _generated(text: str) -> list[dict]:
    """분해 실패·한도 초과·과부하·2개 이하 → []."""
    try:
        [result] = await gemini.call_many(
            [
                {
                    "kind": "phase_split",
                    "system": PromptLoaderService().get_prompt(
                        "sim_phase_split"
                    ),
                    "user": text,
                    "schema": PhaseSplitResult,
                }
            ]
        )
    except SimulationError:
        return []
    if result.parsed is None or len(result.parsed.phases) <= 2:
        return []
    return [_fit(p.model_dump()) for p in result.parsed.phases[:MAX_PHASES]]


async def draft_phases(db: AsyncSession, user_id: int) -> dict:
    """DB에 쓰지 않는다. 업로드가 없으면 NO_UPLOAD."""
    upload = await lessonplan_source.get_latest_upload(db, user_id)
    if upload is None:
        raise SimulationError("NO_UPLOAD")
    # 업로드는 사용자 소유이므로 upload_id만으로 본인 세션으로 좁혀진다
    phases = await _inherited(db, upload.id)
    if phases:
        return {"source": "inherited", "phases": phases, "notice": None}
    text = lessonplan_source.extract_text(upload).strip()
    phases = await _generated(text) if text else []
    if phases:
        return {"source": "generated", "phases": phases, "notice": None}
    return {
        "source": "fallback",
        "phases": fallback_phases(),
        "notice": FALLBACK_NOTICE,
    }
