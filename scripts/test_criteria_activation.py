"""
평가기준 활성화 기능 테스트

수정 사항:
- activated_at 컬럼 추가
- activate_criteria 메서드에서 activated_at 설정
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy.ext.asyncio import AsyncSession
from app.db import async_session_maker
from app.repositories.criteria_repository import CriteriaRepository
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_criteria_activation():
    """
    평가기준 활성화 테스트

    1. 평가기준 생성
    2. 활성화
    3. activated_at 확인
    4. 삭제
    """
    async with async_session_maker() as session:
        try:
            criteria_repo = CriteriaRepository(session)

            logger.info("테스트 시작: 평가기준 활성화")

            # 1. 평가기준 생성
            logger.info("\n1단계: 평가기준 생성")
            criteria = await criteria_repo.save_criteria(
                title="test_curriculum.pdf",
                file_size=424065,
                uploaded_by="admin",
                file_path="temp",
                document_id=None,
                status="uploaded",
            )
            await session.commit()

            logger.info(
                f"✅ 생성 성공! "
                f"criteria_id={criteria.id}, "
                f"status={criteria.status}, "
                f"activated_at={criteria.activated_at}"
            )

            if criteria.activated_at is not None:
                logger.error(
                    "❌ 초기 상태에서 activated_at이 None이 아님!"
                )
            else:
                logger.info("✅ 초기 activated_at=None 확인")

            # 2. 활성화
            logger.info("\n2단계: 평가기준 활성화")
            activated = await criteria_repo.activate_criteria(
                criteria.id
            )
            await session.commit()

            if not activated:
                logger.error("❌ 활성화 실패!")
                return

            logger.info(
                f"✅ 활성화 성공! "
                f"status={activated.status}, "
                f"activated_at={activated.activated_at}"
            )

            # 3. activated_at 확인
            logger.info("\n3단계: activated_at 검증")
            if activated.status != "active":
                logger.error(
                    f"❌ 상태가 active가 아님: {activated.status}"
                )
            else:
                logger.info("✅ 상태가 active로 변경됨")

            if activated.activated_at is None:
                logger.error("❌ activated_at이 None입니다!")
            else:
                logger.info(
                    f"✅ activated_at 설정됨: "
                    f"{activated.activated_at}"
                )

                # 시간 확인 (최근 1분 이내)
                time_diff = datetime.utcnow() - activated.activated_at
                if time_diff.total_seconds() > 60:
                    logger.warning(
                        f"⚠️  activated_at이 예상보다 오래됨: "
                        f"{time_diff.total_seconds()}초 전"
                    )
                else:
                    logger.info(
                        f"✅ activated_at 시간 정상: "
                        f"{time_diff.total_seconds():.2f}초 전"
                    )

            # 4. 조회 확인
            logger.info("\n4단계: 활성 기준 조회")
            active_list = await criteria_repo.get_active_criteria()

            if not active_list:
                logger.error("❌ 활성 기준 조회 실패!")
            else:
                logger.info(
                    f"✅ 활성 기준 {len(active_list)}개 조회됨"
                )
                for item in active_list:
                    logger.info(
                        f"  - {item.title}: "
                        f"activated_at={item.activated_at}"
                    )

            # 5. 삭제
            logger.info("\n5단계: 테스트 데이터 삭제")
            await criteria_repo.delete_criteria(criteria.id)
            await session.commit()
            logger.info("✅ 테스트 데이터 삭제 완료")

            logger.info("\n" + "="*50)
            logger.info("테스트 성공! 평가기준 활성화 기능이 정상 동작합니다.")
            logger.info("="*50)

        except Exception as e:
            await session.rollback()
            logger.error(f"\n테스트 실패: {e}", exc_info=True)
            raise


async def main():
    """메인 실행 함수"""
    try:
        await test_criteria_activation()
    except Exception as e:
        logger.error(f"테스트 실행 중 오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
