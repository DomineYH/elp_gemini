#!/usr/bin/env python3
"""
레거시 평가기준 데이터 안전 삭제 스크립트

목적:
- document_id가 NULL인 레거시 평가기준 레코드를 DB에서만 삭제
- Google API 리소스는 건드리지 않음 (수동 정리 필요)

사용법:
    python scripts/cleanup_legacy_criteria.py [--dry-run]

옵션:
    --dry-run: 실제 삭제 없이 삭제 대상만 출력
"""
import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
)
from sqlalchemy.orm import sessionmaker

from app.models.criteria import CriteriaDocument
from app.config import settings


async def get_legacy_records(
    session: AsyncSession,
) -> list[CriteriaDocument]:
    """
    document_id가 NULL인 레거시 레코드 조회

    Args:
        session: 비동기 세션

    Returns:
        레거시 레코드 리스트
    """
    stmt = select(CriteriaDocument).where(
        CriteriaDocument.document_id.is_(None)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_legacy_records(
    session: AsyncSession, dry_run: bool = False
) -> int:
    """
    레거시 레코드를 DB에서 삭제

    Args:
        session: 비동기 세션
        dry_run: True면 실제 삭제 없이 시뮬레이션

    Returns:
        삭제된 레코드 수
    """
    if dry_run:
        print("\n[DRY-RUN] 실제 삭제는 수행되지 않습니다.\n")
        return 0

    stmt = delete(CriteriaDocument).where(
        CriteriaDocument.document_id.is_(None)
    )
    result = await session.execute(stmt)
    await session.commit()

    return result.rowcount


async def main(dry_run: bool = False):
    """
    메인 실행 함수

    Args:
        dry_run: True면 실제 삭제 없이 시뮬레이션
    """
    print("=" * 70)
    print("레거시 평가기준 데이터 안전 삭제 스크립트")
    print("=" * 70)
    print()

    # 데이터베이스 연결
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
    )
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        # 1. 레거시 레코드 조회
        print("[1/3] 레거시 레코드 조회 중...")
        legacy_records = await get_legacy_records(session)

        if not legacy_records:
            print("\n✅ 레거시 레코드가 없습니다.")
            print("    모든 평가기준이 정상적으로 마이그레이션됨")
            return

        print(
            f"\n⚠️  총 {len(legacy_records)}개의 레거시 "
            "레코드가 발견되었습니다.\n"
        )

        # 2. 삭제 대상 출력
        print("[2/3] 삭제 대상 목록:")
        print("-" * 70)
        print(
            f"{'ID':<5} {'제목':<30} {'스토어 ID':<35}"
        )
        print("-" * 70)

        for record in legacy_records:
            store_id_short = (
                record.vector_store_id[:32] + "..."
                if len(record.vector_store_id) > 35
                else record.vector_store_id
            )
            print(
                f"{record.id:<5} "
                f"{record.title[:27] + '...' if len(record.title) > 30 else record.title:<30} "  # noqa: E501
                f"{store_id_short:<35}"
            )

        print("-" * 70)
        print()

        # 3. 사용자 확인
        if not dry_run:
            print(
                "⚠️  경고: DB에서 레코드가 영구 삭제됩니다."
            )
            print(
                "   Google API 리소스(스토어/문서)는 "
                "수동으로 정리해야 합니다.\n"
            )
            confirm = input("삭제를 진행하시겠습니까? (yes/no): ")

            if confirm.lower() != "yes":
                print("\n❌ 삭제가 취소되었습니다.")
                return

        # 4. 삭제 실행
        print("\n[3/3] 삭제 실행 중...")
        deleted_count = await delete_legacy_records(
            session, dry_run
        )

        # 5. 결과 출력
        print("\n" + "=" * 70)
        if dry_run:
            print(
                f"✅ [DRY-RUN] {len(legacy_records)}개 "
                "레코드가 삭제될 예정입니다."
            )
        else:
            print(
                f"✅ {deleted_count}개 레코드가 삭제되었습니다."
            )
        print("=" * 70)

        # 6. 후속 작업 안내
        if not dry_run and deleted_count > 0:
            print("\n📋 후속 작업:")
            print(
                "1. Google API Console에서 스토어/문서 "
                "수동 정리 (선택)"
            )
            print(
                "2. 필요한 평가기준 재업로드 "
                "(docs/legacy_criteria_migration.md 참조)"
            )
            print(
                f"3. 삭제 로그: {datetime.now().isoformat()}"
            )

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="레거시 평가기준 데이터 안전 삭제"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 삭제 없이 시뮬레이션",
    )

    args = parser.parse_args()

    try:
        asyncio.run(main(dry_run=args.dry_run))
    except KeyboardInterrupt:
        print("\n\n❌ 사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 오류 발생: {e}")
        sys.exit(1)
