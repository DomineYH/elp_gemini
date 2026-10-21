"""
국면 초안. #152는 빈 3행(도입/활동1/정리)만, 자동 국면 분해는 #155.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.simulation import lessonplan_source
from app.services.simulation.errors import SimulationError

FALLBACK_NAMES = ("도입", "활동1", "정리")
FALLBACK_NOTICE = "국면 이름과 교사 발문을 직접 입력해 주세요."


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


async def draft_phases(db: AsyncSession, user_id: int) -> dict:
    """DB에 쓰지 않는다. 업로드가 없으면 NO_UPLOAD."""
    if await lessonplan_source.get_latest_upload(db, user_id) is None:
        raise SimulationError("NO_UPLOAD")
    return {
        "source": "fallback",
        "phases": fallback_phases(),
        "notice": FALLBACK_NOTICE,
    }
