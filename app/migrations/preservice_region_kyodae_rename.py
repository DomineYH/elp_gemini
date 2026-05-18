"""
user_profiles.preservice_university_region 라벨 정규화.

기존 시·도 단독 라벨(서울, 경인, …)을 '서울교대', '경인교대' 등
교육대학교 단위 라벨로 갱신한다. '한국교원대' 값은 '기타'로 흡수한다.
멱등(idempotent)하다.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


PRESERVICE_REGION_RENAME: dict[str, str] = {
    "서울": "서울교대",
    "경인": "경인교대",
    "공주": "공주교대",
    "광주": "광주교대",
    "대구": "대구교대",
    "부산": "부산교대",
    "전주": "전주교대",
    "진주": "진주교대",
    "청주": "청주교대",
    "춘천": "춘천교대",
    "한국교원대": "기타",
}


def _user_profiles_table_exists(sync_conn) -> bool:
    """user_profiles 테이블 존재 여부 확인."""
    return inspect(sync_conn).has_table("user_profiles")


async def rename_preservice_university_regions(
    engine: AsyncEngine,
) -> int:
    """
    옛 region 값을 새 라벨로 일괄 갱신.

    Returns:
        갱신된 행 수. 멱등이므로 이미 새 값이면 0.
    """
    async with engine.begin() as conn:
        table_exists = await conn.run_sync(_user_profiles_table_exists)
        if not table_exists:
            logger.warning(
                "user_profiles 테이블이 없어 region 라벨 정규화를 건너뜀"
            )
            return 0

        total = 0
        for old_value, new_value in PRESERVICE_REGION_RENAME.items():
            result = await conn.execute(
                text(
                    "UPDATE user_profiles "
                    "SET preservice_university_region = :new_value "
                    "WHERE preservice_university_region = :old_value"
                ),
                {"new_value": new_value, "old_value": old_value},
            )
            total += result.rowcount or 0

        if total:
            logger.info(
                "user_profiles.preservice_university_region 라벨 갱신 "
                "행 수: %d",
                total,
            )
        return total
