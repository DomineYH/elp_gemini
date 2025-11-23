"""
평가기준 activated_at 컬럼 추가 마이그레이션

문제:
- 템플릿에서 activated_at 속성 사용
- Criteria 모델과 DB에 해당 컬럼 없음

해결:
- activated_at 컬럼을 nullable로 추가
- active 상태일 때만 값 존재
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


async def add_activated_at_column():
    """
    criteria.activated_at 컬럼 추가

    SQLite는 ALTER TABLE ADD COLUMN을 지원하므로 간단히 추가 가능
    """
    async with engine.begin() as conn:
        logger.info("마이그레이션 시작: criteria.activated_at 컬럼 추가")

        # 컬럼 존재 확인
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM pragma_table_info('criteria') "
            "WHERE name = 'activated_at'"
        ))
        exists = result.scalar() > 0

        if exists:
            logger.info("activated_at 컬럼이 이미 존재합니다. 건너뜁니다.")
            return

        # 컬럼 추가
        logger.info("activated_at 컬럼 추가 중...")
        await conn.execute(text(
            "ALTER TABLE criteria "
            "ADD COLUMN activated_at DATETIME"
        ))

        logger.info("✅ activated_at 컬럼 추가 완료!")

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
            "WHERE name = 'activated_at'"
        ))
        exists = result.scalar() > 0

        if exists:
            logger.info("✅ activated_at 컬럼 존재 확인!")
        else:
            logger.error("❌ activated_at 컬럼이 없습니다!")
            raise Exception("마이그레이션 실패")

        # 컬럼 정보 확인
        result = await conn.execute(text(
            "SELECT * FROM pragma_table_info('criteria') "
            "WHERE name = 'activated_at'"
        ))
        column_info = result.fetchone()
        logger.info(f"컬럼 정보: {column_info}")


async def main():
    """메인 실행 함수"""
    try:
        # 마이그레이션 실행
        await add_activated_at_column()

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
