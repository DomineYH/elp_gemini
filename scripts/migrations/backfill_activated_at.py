"""
기존 active 상태 평가기준의 activated_at 백필

문제:
- 기존에 활성화된 데이터가 activated_at이 NULL인 상태
- 새로운 로직에서는 activated_at 필요

해결:
- active 상태인데 activated_at이 NULL인 레코드를
- created_at 값으로 activated_at 설정
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


async def backfill_activated_at():
    """
    기존 active 데이터의 activated_at 백필

    - status='active'이면서 activated_at이 NULL인 레코드
    - created_at 값으로 activated_at 설정
    """
    async with engine.begin() as conn:
        logger.info("백필 시작: active 상태의 activated_at")

        # 대상 레코드 확인
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM criteria "
            "WHERE status = 'active' AND activated_at IS NULL"
        ))
        count = result.scalar()

        if count == 0:
            logger.info("백필 대상 없음. 종료합니다.")
            return

        logger.info(f"백필 대상: {count}건")

        # 백필 실행
        result = await conn.execute(text(
            "UPDATE criteria "
            "SET activated_at = created_at "
            "WHERE status = 'active' AND activated_at IS NULL"
        ))

        updated = result.rowcount
        logger.info(f"✅ {updated}건 업데이트 완료!")

        # 결과 확인
        result = await conn.execute(text(
            "SELECT id, title, status, activated_at "
            "FROM criteria "
            "WHERE status = 'active'"
        ))

        logger.info("\n활성 평가기준 목록:")
        for row in result:
            logger.info(
                f"  - ID: {row[0]}, "
                f"제목: {row[1]}, "
                f"상태: {row[2]}, "
                f"활성화 시각: {row[3]}"
            )


async def main():
    """메인 실행 함수"""
    try:
        await backfill_activated_at()

        logger.info("\n" + "="*50)
        logger.info("백필이 성공적으로 완료되었습니다!")
        logger.info("="*50)

    except Exception as e:
        logger.error(f"\n백필 실패: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
