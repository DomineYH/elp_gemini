"""
일반 사용자 프로필 테이블 보정 도우미

기존 관리자와 초대코드 사용자는 프로필 없이도 계속 동작해야 하므로
백필 없이 1:1 프로필 테이블만 생성한다.
"""
from __future__ import annotations

import logging
from typing import Tuple

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

# app.main startup 전에 SQLAlchemy metadata에 UserProfile을 등록한다.
from app.models.user_profiles import UserProfile  # noqa: F401

logger = logging.getLogger(__name__)


def _collect_profile_table_state(sync_conn) -> Tuple[bool, bool]:
    inspector = inspect(sync_conn)
    table_names = set(inspector.get_table_names())
    return "users" in table_names, "user_profiles" in table_names


async def ensure_user_profiles_table(engine: AsyncEngine) -> bool:
    """
    user_profiles 테이블을 런타임에 생성한다.

    Returns:
        테이블이 새로 생성되었으면 True, 이미 존재하거나 users 테이블이
        없어 건너뛰면 False
    """
    async with engine.begin() as conn:
        users_exists, profile_exists = await conn.run_sync(
            _collect_profile_table_state
        )

        if profile_exists:
            logger.debug(
                "user_profiles 테이블이 이미 존재하여 패치를 건너뜀"
            )
            return False

        if not users_exists:
            logger.warning(
                "users 테이블이 없어 user_profiles 생성을 건너뜀"
            )
            return False

        await conn.execute(
            text(
                """
                CREATE TABLE user_profiles (
                    id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role VARCHAR(50) NOT NULL,
                    teacher_region VARCHAR(50),
                    teacher_career_years INTEGER,
                    preservice_university_region VARCHAR(50),
                    preservice_grade INTEGER,
                    created_at DATETIME NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE (user_id),
                    CONSTRAINT ck_user_profiles_role
                        CHECK (
                            role IN (
                                'teacher',
                                'preservice_teacher'
                            )
                        ),
                    CONSTRAINT
                        ck_user_profiles_teacher_career_years_non_negative
                        CHECK (
                            teacher_career_years IS NULL
                            OR teacher_career_years >= 0
                        ),
                    CONSTRAINT ck_user_profiles_preservice_grade_range
                        CHECK (
                            preservice_grade IS NULL
                            OR preservice_grade BETWEEN 1 AND 4
                        ),
                    FOREIGN KEY(user_id)
                        REFERENCES users (id)
                        ON DELETE CASCADE
                )
                """
            )
        )

        logger.info("user_profiles 테이블 생성 완료")
        return True
