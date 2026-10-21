"""
내 학생 페르소나 라이브러리: 저장 시 1회 번안, 세션에는 복사본으로 들어간다.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.simulation_persona_library import (
    SimulationPersonaLibraryItem,
)
from app.services.simulation import persona_pool
from app.services.simulation.adaptation import adapt_many
from app.services.simulation.errors import SimulationError


def ref(item: SimulationPersonaLibraryItem) -> str:
    return f"custom:{item.id}"


def to_out(item: SimulationPersonaLibraryItem) -> dict:
    return {
        "id": item.id,
        "ref": ref(item),
        "raw_profile": item.raw_profile,
        "adapted_profile": item.adapted_profile,
        "adapted_level": item.adapted_level,
        "created_at": item.created_at,
    }


def to_candidate(item: SimulationPersonaLibraryItem, pseudonym: str) -> dict:
    return {
        **persona_pool.to_candidate(
            {**item.raw_profile, "id": item.id}, pseudonym
        ),
        "ref": ref(item),
        "source": "custom",
        # 저장 시 번안한 한국어 요약을 보인다 (#177)
        "behavior_summary": persona_pool.summarize(
            item.adapted_profile["behavior_summary"]
        ),
    }


async def create(
    db: AsyncSession, user_id: int, profile: dict
) -> SimulationPersonaLibraryItem:
    [(adapted, level)] = await adapt_many([(None, profile)])
    item = SimulationPersonaLibraryItem(
        user_id=user_id,
        raw_profile=profile,
        adapted_profile=adapted,
        adapted_level=level,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def list_items(
    db: AsyncSession, user_id: int
) -> list[SimulationPersonaLibraryItem]:
    return list(
        await db.scalars(
            select(SimulationPersonaLibraryItem)
            .where(SimulationPersonaLibraryItem.user_id == user_id)
            .order_by(SimulationPersonaLibraryItem.id)
        )
    )


async def delete(db: AsyncSession, user_id: int, item_id: int) -> None:
    item = await db.scalar(
        select(SimulationPersonaLibraryItem).where(
            SimulationPersonaLibraryItem.id == item_id,
            SimulationPersonaLibraryItem.user_id == user_id,
        )
    )
    if item is None:
        raise SimulationError("LIBRARY_NOT_FOUND")
    await db.delete(item)
    await db.commit()


async def snapshot_for_session(
    db: AsyncSession, user_id: int, ids: list[int]
) -> list[SimulationPersonaLibraryItem]:
    """ids 순서대로. 없거나 남의 항목 → UNKNOWN_PERSONA."""
    by_id = {
        item.id: item
        for item in await db.scalars(
            select(SimulationPersonaLibraryItem).where(
                SimulationPersonaLibraryItem.id.in_(ids),
                SimulationPersonaLibraryItem.user_id == user_id,
            )
        )
    }
    if any(i not in by_id for i in ids):
        raise SimulationError("UNKNOWN_PERSONA")
    return [by_id[i] for i in ids]
