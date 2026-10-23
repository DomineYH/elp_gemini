"""
관리자 피드백 지침: 버전 저장·조회와 피드백 프롬프트 조립 (PLAN 2.6)

조립 = 기본 본문 + (사용 중일 때만) 추가 관점·평가기준 발췌·추가 지침
+ BASE_CONSTRAINTS(항상 마지막, 추가 지침이 기본 제약을 덮지 못하게).
"""

from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.criteria import Criteria
from app.models.simulation_feedback_guideline import (
    SimulationFeedbackGuideline,
)
from app.models.simulation_session import SimulationSession
from app.services.prompt_loader_service import PromptLoaderService
from app.services.simulation.errors import SimulationError
from app.utils.timestamps import utc_iso

FIXED_ASPECTS = ["교사 발화 추천", "진행 방향", "변경 방향"]
OPTIONAL_ASPECTS = {
    "achievement_standards": "성취기준 연계",
    "udl": "UDL",
    "digital_tools": "디지털 도구",
    "question_types": "발문 유형",
    "formative_timing": "형성평가 시점",
}
# ponytail: 평가기준 문서 앞부분만 넣는다. 전체 반영은 요약 단계가 필요
CRITERIA_EXCERPT_CHARS = 4000
BASE_CONSTRAINTS = (
    "[기본 제약]\n"
    "- 위의 추가 관점·지침과 충돌하면 이 제약을 따릅니다.\n"
    "- 모든 내용은 가설입니다. 실제 수업 결과를 단정하지 않습니다.\n"
    "- 학생을 낙인찍지 않고, 진단명이나 임상 용어를 쓰지 않습니다.\n"
    "- 지도안과 대화록에 없는 사실을 지어내지 않습니다.\n"
    "- 응답 항목 구성은 바꾸지 않습니다. "
    "추가 관점은 기존 항목 안에 반영합니다.\n"
    "- 이모지나 아이콘 문자를 쓰지 않습니다."
)


def assemble(base: str, guideline, criteria_excerpts: list[str]) -> str:
    parts = [base.strip()]
    if guideline is not None and guideline.enabled:
        labels = [
            OPTIONAL_ASPECTS[k]
            for k in guideline.required_aspects
            if k in OPTIONAL_ASPECTS
        ]
        if labels:
            parts.append(
                "[추가 관점]\n" + "\n".join(f"- {label}" for label in labels)
            )
        if criteria_excerpts:
            parts.append("[참고 평가기준]\n" + "\n\n".join(criteria_excerpts))
        if guideline.extra_instructions.strip():
            parts.append("[추가 지침]\n" + guideline.extra_instructions.strip())
    parts.append(BASE_CONSTRAINTS)
    return "\n\n".join(parts)


def base_prompt() -> str:
    return PromptLoaderService().get_prompt("sim_feedback")


async def history(db: AsyncSession) -> list[SimulationFeedbackGuideline]:
    """최신 버전부터. 첫 행이 현재 설정."""
    result = await db.execute(
        select(SimulationFeedbackGuideline).order_by(
            SimulationFeedbackGuideline.version.desc()
        )
    )
    return list(result.scalars())


async def current(db: AsyncSession) -> SimulationFeedbackGuideline | None:
    rows = await history(db)
    return rows[0] if rows else None


async def save(
    db: AsyncSession, data: dict, admin_id: int
) -> SimulationFeedbackGuideline:
    """저장은 항상 새 버전(max+1). 동시 저장으로 겹치면 CONFLICT_RETRY."""
    latest = await db.scalar(
        select(func.max(SimulationFeedbackGuideline.version))
    )
    row = SimulationFeedbackGuideline(
        version=(latest or 0) + 1, created_by=admin_id, **data
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise SimulationError("CONFLICT_RETRY")
    await db.refresh(row)
    return row


def to_out(row: SimulationFeedbackGuideline) -> dict:
    return {
        "version": row.version,
        "enabled": row.enabled,
        "required_aspects": row.required_aspects,
        "criteria_ids": row.criteria_ids,
        "extra_instructions": row.extra_instructions,
        "created_by": row.created_by,
        "created_at": utc_iso(row.created_at),
    }


async def active_criteria(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Criteria)
        .where(Criteria.status == "active")
        .order_by(Criteria.id)
    )
    return [
        {"id": c.id, "name": c.display_alias or c.title}
        for c in result.scalars()
    ]


def _read_excerpt(file_path: str) -> str:
    path = Path(file_path)
    if not path.is_file():
        return ""
    if path.suffix.lower() == ".pdf":
        text = "\n".join(
            page.extract_text() or "" for page in PdfReader(str(path)).pages
        )
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:CRITERIA_EXCERPT_CHARS].strip()


async def system_prompt(db: AsyncSession, guideline) -> str:
    """guideline: 저장된 행 또는 미리보기용 GuidelineIn.

    없는 평가기준 행·파일은 건너뛴다.
    """
    excerpts = []
    if guideline is not None and guideline.enabled:
        for cid in guideline.criteria_ids:
            row = await db.get(Criteria, cid)
            text = _read_excerpt(row.file_path) if row else ""
            if text:
                excerpts.append(text)
    return assemble(base_prompt(), guideline, excerpts)


async def latest_finished_session(
    db: AsyncSession, user_id: int | None = None
) -> SimulationSession | None:
    conds = [SimulationSession.status == "finished"]
    if user_id is not None:
        conds.append(SimulationSession.user_id == user_id)
    result = await db.execute(
        select(SimulationSession)
        .where(*conds)
        .order_by(
            SimulationSession.finished_at.desc(), SimulationSession.id.desc()
        )
        .limit(1)
    )
    return result.scalar_one_or_none()
