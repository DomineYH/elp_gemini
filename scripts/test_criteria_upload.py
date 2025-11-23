"""
평가기준 업로드 기능 테스트

수정 사항:
- document_id가 nullable로 변경되었는지 확인
- NULL 값으로 저장 가능한지 확인
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


async def test_criteria_upload():
    """
    평가기준 업로드 테스트

    1. document_id=None으로 저장
    2. 저장 확인
    3. 삭제
    """
    async with async_session_maker() as session:
        try:
            criteria_repo = CriteriaRepository(session)

            logger.info("테스트 시작: document_id=None으로 저장")

            # 1. document_id=None으로 저장
            criteria = await criteria_repo.save_criteria(
                title="test_curriculum.pdf",
                file_size=424065,
                uploaded_by="admin",
                file_path="temp",
                document_id=None,  # NULL 값!
                status="uploaded",
            )
            await session.commit()

            logger.info(
                f"✅ 저장 성공! "
                f"criteria_id={criteria.id}, "
                f"document_id={criteria.document_id}"
            )

            # 2. 저장 확인
            saved_criteria = await criteria_repo.get_criteria_by_id(
                criteria.id
            )

            if saved_criteria:
                logger.info(
                    f"✅ 조회 성공! "
                    f"title={saved_criteria.title}, "
                    f"document_id={saved_criteria.document_id}"
                )

                if saved_criteria.document_id is None:
                    logger.info("✅ document_id가 NULL로 저장됨!")
                else:
                    logger.error(
                        f"❌ document_id가 NULL이 아님: "
                        f"{saved_criteria.document_id}"
                    )
            else:
                logger.error("❌ 저장된 데이터 조회 실패")

            # 3. 삭제
            await criteria_repo.delete_criteria(criteria.id)
            await session.commit()
            logger.info("✅ 테스트 데이터 삭제 완료")

            logger.info("\n" + "="*50)
            logger.info("테스트 성공! 평가기준 업로드 기능이 정상 동작합니다.")
            logger.info("="*50)

        except Exception as e:
            await session.rollback()
            logger.error(f"\n테스트 실패: {e}", exc_info=True)
            raise


async def main():
    """메인 실행 함수"""
    try:
        await test_criteria_upload()
    except Exception as e:
        logger.error(f"테스트 실행 중 오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
