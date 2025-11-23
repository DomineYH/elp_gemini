"""
평가기준 document_id 컬럼을 nullable로 변경하는 마이그레이션

문제:
- 모델에서는 document_id가 nullable=True
- 실제 DB에서는 NOT NULL 제약조건이 있음
- 업로드 시 document_id=None으로 저장해야 하는데 제약조건 위반

해결:
- SQLite는 ALTER COLUMN을 지원하지 않으므로
- 테이블 재생성 방식 사용
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


async def migrate_criteria_document_id_nullable():
    """
    criteria.document_id를 nullable로 변경

    SQLite는 ALTER TABLE ... ALTER COLUMN을 지원하지 않으므로
    테이블 재생성 방식 사용:
    1. 새 테이블 생성 (올바른 스키마)
    2. 데이터 복사
    3. 기존 테이블 삭제
    4. 새 테이블 이름 변경
    5. 인덱스 재생성
    """
    async with engine.begin() as conn:
        logger.info("마이그레이션 시작: criteria.document_id nullable 변경")

        # 1. 기존 데이터 확인
        result = await conn.execute(
            text("SELECT COUNT(*) FROM criteria")
        )
        count = result.scalar()
        logger.info(f"기존 데이터: {count}건")

        # 2. 새 테이블 생성 (올바른 스키마)
        logger.info("새 테이블 생성 중...")
        await conn.execute(text("""
            CREATE TABLE criteria_new (
                id INTEGER NOT NULL,
                title VARCHAR(255) NOT NULL,
                document_id VARCHAR(500),  -- NULL 허용!
                file_size BIGINT NOT NULL,
                file_path VARCHAR(500) NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
                uploaded_by VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id)
            )
        """))

        # 3. 데이터 복사
        if count > 0:
            logger.info(f"데이터 복사 중... ({count}건)")
            await conn.execute(text("""
                INSERT INTO criteria_new
                    (id, title, document_id, file_size, file_path,
                     status, uploaded_by, created_at, updated_at)
                SELECT
                    id, title, document_id, file_size, file_path,
                    status, uploaded_by, created_at, updated_at
                FROM criteria
            """))
            logger.info("데이터 복사 완료")

        # 4. 기존 테이블 삭제
        logger.info("기존 테이블 삭제 중...")
        await conn.execute(text("DROP TABLE criteria"))

        # 5. 새 테이블 이름 변경
        logger.info("새 테이블 이름 변경 중...")
        await conn.execute(text(
            "ALTER TABLE criteria_new RENAME TO criteria"
        ))

        # 6. 인덱스 재생성
        logger.info("인덱스 재생성 중...")
        await conn.execute(text(
            "CREATE INDEX ix_criteria_id ON criteria (id)"
        ))
        await conn.execute(text(
            "CREATE INDEX ix_criteria_status ON criteria (status)"
        ))
        await conn.execute(text(
            "CREATE INDEX ix_criteria_created_at ON criteria (created_at)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX ix_criteria_document_id "
            "ON criteria (document_id) "
            "WHERE document_id IS NOT NULL"  # NULL 값은 UNIQUE 제약에서 제외
        ))

        logger.info("✅ 마이그레이션 완료!")
        logger.info("document_id는 이제 NULL을 허용합니다.")

        # 7. 결과 확인
        result = await conn.execute(
            text("SELECT COUNT(*) FROM criteria")
        )
        new_count = result.scalar()
        logger.info(f"마이그레이션 후 데이터: {new_count}건")

        if new_count == count:
            logger.info("✅ 데이터 무결성 확인 완료")
        else:
            logger.error(
                f"❌ 데이터 손실 발생! "
                f"이전: {count}건, 이후: {new_count}건"
            )
            raise Exception("데이터 손실 감지")


async def verify_migration():
    """마이그레이션 결과 검증"""
    async with engine.begin() as conn:
        logger.info("\n검증 시작...")

        # 스키마 확인
        result = await conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name='criteria'")
        )
        schema = result.scalar()
        logger.info(f"새 스키마:\n{schema}")

        # NULL 값 삽입 테스트
        logger.info("\nNULL 값 삽입 테스트...")
        try:
            await conn.execute(text("""
                INSERT INTO criteria
                    (title, document_id, file_size, file_path,
                     status, uploaded_by)
                VALUES
                    ('test.pdf', NULL, 100, '/test', 'uploaded', 'admin')
            """))

            # 방금 삽입한 데이터 삭제
            await conn.execute(text(
                "DELETE FROM criteria WHERE title = 'test.pdf'"
            ))

            logger.info("✅ NULL 값 삽입 테스트 성공!")
        except Exception as e:
            logger.error(f"❌ NULL 값 삽입 테스트 실패: {e}")
            raise


async def main():
    """메인 실행 함수"""
    try:
        # 마이그레이션 실행
        await migrate_criteria_document_id_nullable()

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
