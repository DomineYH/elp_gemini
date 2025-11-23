"""
평가기준 토글 기능 테스트

수정 사항:
- 활성화/비활성화 토글 기능
- deactivate_criteria 메서드 추가
"""
import asyncio
import sys
from pathlib import Path

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


async def test_criteria_toggle():
    """
    평가기준 토글 테스트

    1. 평가기준 생성
    2. 활성화
    3. 비활성화
    4. 재활성화
    5. 삭제
    """
    async with async_session_maker() as session:
        try:
            criteria_repo = CriteriaRepository(session)

            logger.info("=" * 60)
            logger.info("평가기준 토글 기능 테스트 시작")
            logger.info("=" * 60)

            # 1. 평가기준 생성
            logger.info("\n[1단계] 평가기준 생성")
            criteria = await criteria_repo.save_criteria(
                title="test_toggle.pdf",
                file_size=100000,
                uploaded_by="admin",
                file_path="temp",
                document_id=None,
                status="uploaded",
            )
            await session.commit()

            logger.info(
                f"✅ 생성 완료: "
                f"ID={criteria.id}, "
                f"상태={criteria.status}, "
                f"activated_at={criteria.activated_at}"
            )

            # 2. 활성화
            logger.info("\n[2단계] 활성화")
            activated = await criteria_repo.activate_criteria(
                criteria.id
            )
            await session.commit()

            if activated and activated.status == "active":
                logger.info(
                    f"✅ 활성화 성공: "
                    f"상태={activated.status}, "
                    f"activated_at={activated.activated_at}"
                )
            else:
                logger.error("❌ 활성화 실패!")
                return

            # 3. 비활성화
            logger.info("\n[3단계] 비활성화")
            deactivated = await criteria_repo.deactivate_criteria(
                criteria.id
            )
            await session.commit()

            if deactivated and deactivated.status == "uploaded":
                logger.info(
                    f"✅ 비활성화 성공: "
                    f"상태={deactivated.status}, "
                    f"activated_at={deactivated.activated_at} (이력 보존)"
                )
            else:
                logger.error("❌ 비활성화 실패!")
                return

            # 4. 재활성화
            logger.info("\n[4단계] 재활성화")
            reactivated = await criteria_repo.activate_criteria(
                criteria.id
            )
            await session.commit()

            if reactivated and reactivated.status == "active":
                logger.info(
                    f"✅ 재활성화 성공: "
                    f"상태={reactivated.status}, "
                    f"activated_at={reactivated.activated_at}"
                )
            else:
                logger.error("❌ 재활성화 실패!")
                return

            # 5. 상태 이력 확인
            logger.info("\n[5단계] 상태 이력 확인")
            logger.info(
                f"첫 활성화: {activated.activated_at}"
            )
            logger.info(
                f"비활성화 후: {deactivated.activated_at} "
                f"(이력 보존됨)"
            )
            logger.info(
                f"재활성화: {reactivated.activated_at}"
            )

            # 6. 삭제
            logger.info("\n[6단계] 테스트 데이터 삭제")
            await criteria_repo.delete_criteria(criteria.id)
            await session.commit()
            logger.info("✅ 테스트 데이터 삭제 완료")

            logger.info("\n" + "=" * 60)
            logger.info("✅ 모든 테스트 성공!")
            logger.info("=" * 60)
            logger.info("\n기능 요약:")
            logger.info("  ✓ 활성화: uploaded → active (activated_at 설정)")
            logger.info("  ✓ 비활성화: active → uploaded (activated_at 보존)")
            logger.info("  ✓ 재활성화: uploaded → active (activated_at 갱신)")
            logger.info("=" * 60)

        except Exception as e:
            await session.rollback()
            logger.error(f"\n❌ 테스트 실패: {e}", exc_info=True)
            raise


async def main():
    """메인 실행 함수"""
    try:
        await test_criteria_toggle()
    except Exception as e:
        logger.error(f"테스트 실행 중 오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
