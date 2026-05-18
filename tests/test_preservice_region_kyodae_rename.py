"""
예비교사 region 마이그레이션 검증.

issue #70: 기존 user_profiles.preservice_university_region의 옛 값
(서울/경인/공주/광주/대구/부산/전주/진주/청주/춘천)을 '…교대' 새 값으로
갱신하고, '한국교원대'는 '기타'로 매핑한다. 멱등성을 만족해야 한다.
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.migrations.preservice_region_kyodae_rename import (
    PRESERVICE_REGION_RENAME,
    rename_preservice_university_regions,
)


@pytest_asyncio.fixture
async def memory_engine():
    """인메모리 SQLite 엔진. user_profiles 포함 전체 테이블 생성."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def _insert_profile(engine, role, region):
    """user_profiles 단건 삽입. role/region만 다르게."""
    async with engine.begin() as conn:
        # users 테이블 1행을 먼저 삽입 (FK 제약 만족용)
        result = await conn.execute(
            text(
                "INSERT INTO users (username, nickname, "
                "hashed_password, is_admin) "
                "VALUES (:u, :n, :p, 0)"
            ),
            {"u": f"u-{region}", "n": "n", "p": "p"},
        )
        user_id = result.lastrowid
        await conn.execute(
            text(
                "INSERT INTO user_profiles (user_id, role, "
                "preservice_university_region) "
                "VALUES (:uid, :r, :reg)"
            ),
            {"uid": user_id, "r": role, "reg": region},
        )


@pytest.mark.asyncio
async def test_rename_mapping_covers_all_legacy_values():
    """매핑 테이블이 옛 11개 값을 모두 포함한다."""
    expected_keys = {
        "서울", "경인", "공주", "광주", "대구", "부산",
        "전주", "진주", "청주", "춘천", "한국교원대",
    }
    assert set(PRESERVICE_REGION_RENAME.keys()) == expected_keys


@pytest.mark.asyncio
async def test_rename_updates_legacy_region(memory_engine):
    """옛 값 '대구' → '대구교대'로 갱신된다."""
    await _insert_profile(
        memory_engine, "preservice_teacher", "대구"
    )

    updated = await rename_preservice_university_regions(memory_engine)

    assert updated == 1
    async with memory_engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT preservice_university_region "
                "FROM user_profiles"
            )
        )
        assert row.scalar() == "대구교대"


@pytest.mark.asyncio
async def test_rename_maps_kornu_to_etc(memory_engine):
    """'한국교원대' → '기타'로 매핑된다."""
    await _insert_profile(
        memory_engine, "preservice_teacher", "한국교원대"
    )

    await rename_preservice_university_regions(memory_engine)

    async with memory_engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT preservice_university_region "
                "FROM user_profiles"
            )
        )
        assert row.scalar() == "기타"


@pytest.mark.asyncio
async def test_rename_idempotent(memory_engine):
    """이미 새 값이면 두 번째 호출은 0 행을 갱신."""
    await _insert_profile(
        memory_engine, "preservice_teacher", "서울"
    )

    first = await rename_preservice_university_regions(memory_engine)
    second = await rename_preservice_university_regions(memory_engine)

    assert first == 1
    assert second == 0


@pytest.mark.asyncio
async def test_rename_leaves_unknown_values(memory_engine):
    """매핑에 없는 값(예: 이미 신규 값)은 건드리지 않는다."""
    await _insert_profile(
        memory_engine, "preservice_teacher", "서울교대"
    )

    updated = await rename_preservice_university_regions(memory_engine)

    assert updated == 0
    async with memory_engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT preservice_university_region "
                "FROM user_profiles"
            )
        )
        assert row.scalar() == "서울교대"


@pytest.mark.asyncio
async def test_rename_skips_when_table_missing():
    """user_profiles 테이블이 없으면 0을 반환하고 예외 없음."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        result = await rename_preservice_university_regions(engine)
    finally:
        await engine.dispose()
    assert result == 0
