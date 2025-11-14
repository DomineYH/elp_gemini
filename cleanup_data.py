"""
데이터베이스 정리 스크립트
중복 사용자 계정 및 문서 정리
"""
import asyncio
import sqlite3
from app.services.file_search_service import FileSearchService
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def cleanup_vector_db():
    """Vector DB에서 문서 삭제"""
    logger.info("=== Vector DB 정리 시작 ===")

    # Local DB에서 삭제할 문서 ID 조회
    conn = sqlite3.connect('data/app.db')
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, file_search_file_id, store_id, user_id
        FROM documents
        WHERE file_search_file_id IS NOT NULL
        ORDER BY id
    """)

    documents = cursor.fetchall()
    conn.close()

    if not documents:
        logger.info("Vector DB에 삭제할 문서가 없습니다.")
        return

    fs_service = FileSearchService()

    for doc_id, title, file_search_file_id, store_id, user_id in documents:
        try:
            logger.info(f"문서 삭제 시도: id={doc_id}, title={title}, user_id={user_id}")
            await fs_service.delete_document(file_id=file_search_file_id)
            logger.info(f"✅ 문서 삭제 완료: {title}")
        except Exception as e:
            logger.warning(f"⚠️ 문서 삭제 실패 (이미 삭제되었을 수 있음): {str(e)}")

    logger.info("=== Vector DB 정리 완료 ===\n")


def cleanup_local_db():
    """Local DB에서 중복 사용자 및 문서 삭제"""
    logger.info("=== Local DB 정리 시작 ===")

    conn = sqlite3.connect('data/app.db')
    cursor = conn.cursor()

    # 1. 현재 상태 확인
    cursor.execute("SELECT COUNT(*) FROM users WHERE id > 2")
    duplicate_users_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM documents")
    documents_count = cursor.fetchone()[0]

    logger.info(f"중복 사용자: {duplicate_users_count}명")
    logger.info(f"전체 문서: {documents_count}개")

    # 2. QA 로그 삭제 (외래키 제약)
    cursor.execute("DELETE FROM qa_logs WHERE document_id IN (SELECT id FROM documents)")
    deleted_qa_logs = cursor.rowcount
    logger.info(f"QA 로그 삭제: {deleted_qa_logs}개")

    # 3. 모든 문서 삭제
    cursor.execute("DELETE FROM documents")
    deleted_docs = cursor.rowcount
    logger.info(f"문서 삭제: {deleted_docs}개")

    # 4. 중복 사용자 삭제 (id > 2, admin과 user_id=2 제외)
    cursor.execute("DELETE FROM users WHERE id > 2")
    deleted_users = cursor.rowcount
    logger.info(f"중복 사용자 삭제: {deleted_users}명")

    # 5. 변경사항 커밋
    conn.commit()

    # 6. 최종 상태 확인
    cursor.execute("SELECT id, username, nickname FROM users ORDER BY id")
    remaining_users = cursor.fetchall()
    logger.info(f"\n남은 사용자:")
    for user in remaining_users:
        logger.info(f"  - id={user[0]}, username={user[1]}, nickname={user[2]}")

    cursor.execute("SELECT COUNT(*) FROM documents")
    remaining_docs = cursor.fetchone()[0]
    logger.info(f"남은 문서: {remaining_docs}개")

    conn.close()
    logger.info("=== Local DB 정리 완료 ===\n")


async def main():
    """메인 실행 함수"""
    logger.info("=" * 50)
    logger.info("데이터베이스 정리 시작")
    logger.info("=" * 50 + "\n")

    try:
        # 1. Vector DB 정리
        await cleanup_vector_db()

        # 2. Local DB 정리
        cleanup_local_db()

        logger.info("=" * 50)
        logger.info("✅ 모든 정리 작업 완료!")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"❌ 정리 작업 중 오류 발생: {str(e)}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
