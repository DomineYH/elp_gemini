"""
평가기준 synced_at 컬럼 추가 마이그레이션

목적:
- Vector Store 동기화 상태 추적을 위한 synced_at 컬럼 추가
- 토글 변경 시 즉시 동기화 대신 '활성화 확정' 버튼으로 일괄 동기화
- synced_at이 NULL이거나 updated_at보다 이전이면 동기화 필요

해결:
- synced_at 컬럼을 nullable로 추가
- 기존 active 상태의 문서는 synced_at = updated_at으로 초기화
"""
import asyncio
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from app.db import engine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def add_synced_at_column():
    """
    criteria.synced_at 컬럼 추가

    SQLite는 ALTER TABLE ADD COLUMN을 지원하므로 간단히 추가 가능
    """
    async with engine.begin() as conn:
        logger.info("마이그레이션 시작: criteria.synced_at 컬럼 추가")

        # 컬럼 존재 확인
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM pragma_table_info('criteria') "
            "WHERE name = 'synced_at'"
        ))
        exists = result.scalar() > 0

        if exists:
            logger.info("synced_at 컬럼이 이미 존재합니다. 건너뜁니다.")
            return

        # 컬럼 추가
        logger.info("synced_at 컬럼 추가 중...")
        await conn.execute(text(
            "ALTER TABLE criteria "
            "ADD COLUMN synced_at DATETIME"
        ))

        logger.info("✅ synced_at 컬럼 추가 완료!")

        # 기존 active 상태 문서의 synced_at 초기화
        logger.info("기존 active 문서의 synced_at 초기화 중...")
        result = await conn.execute(text(
            "UPDATE criteria "
            "SET synced_at = updated_at "
            "WHERE status = 'active' AND document_id IS NOT NULL"
        ))
        updated_count = result.rowcount
        logger.info(f"✅ {updated_count}개 문서의 synced_at 초기화 완료!")

        # 스키마 확인
        result = await conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name='criteria'")
        )
        schema = result.scalar()
        logger.info(f"\n새 스키마:\n{schema}")


async def verify_migration():
    """마이그레이션 결과 검증"""
    async with engine.begin() as conn:
        logger.info("\n검증 시작...")

        # 컬럼 존재 확인
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM pragma_table_info('criteria') "
            "WHERE name = 'synced_at'"
        ))
        exists = result.scalar() > 0

        if exists:
            logger.info("✅ synced_at 컬럼 존재 확인!")
        else:
            logger.error("❌ synced_at 컬럼이 없습니다!")
            raise Exception("마이그레이션 실패")

        # 컬럼 정보 확인
        result = await conn.execute(text(
            "SELECT * FROM pragma_table_info('criteria') "
            "WHERE name = 'synced_at'"
        ))
        column_info = result.fetchone()
        logger.info(f"컬럼 정보: {column_info}")

        # 초기화된 데이터 확인
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM criteria "
            "WHERE status = 'active' AND synced_at IS NOT NULL"
        ))
        synced_count = result.scalar()
        logger.info(f"동기화 시각이 설정된 active 문서: {synced_count}개")


async def main():
    """메인 실행 함수"""
    try:
        # 마이그레이션 실행
        await add_synced_at_column()

        # 검증
        await verify_migration()

        logger.info("\n" + "="*50)
        logger.info("마이그레이션이 성공적으로 완료되었습니다!")
        logger.info("="*50)

    except Exception as e:
        logger.error(f"\n마이그레이션 실패: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
