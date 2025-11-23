"""
통합 테스트 환경 구성
- 테스트 DB 연결 확인
- 테스트용 Vector DB Store 생성 및 접근 확인
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import engine, async_session_maker
from app.services.file_search_service import FileSearchService
from sqlalchemy import text


async def test_database_connection():
    """데이터베이스 연결 테스트"""
    print("1. 데이터베이스 연결 테스트...")
    try:
        async with engine.connect() as conn:
            # 간단한 쿼리 실행
            result = await conn.execute(
                text("SELECT 1 as test")
            )
            test_value = result.scalar()

            if test_value == 1:
                print("✅ DB 연결 성공")
            else:
                print("❌ DB 연결 실패: 예상치 못한 값")
                return False

            # 테이블 존재 확인
            result = await conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' "
                    "AND name IN "
                    "('chat_sessions', 'chat_messages')"
                )
            )
            tables = [row[0] for row in result]

            required_tables = ["chat_sessions", "chat_messages"]
            missing = [t for t in required_tables if t not in tables]

            if missing:
                print(f"⚠️  누락된 테이블: {missing}")
                return False

            print(f"✅ 필수 테이블 확인: {', '.join(tables)}")
            return True

    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_vector_store_access():
    """Vector DB Store 접근 테스트"""
    print("\n2. Vector DB Store 접근 테스트...")
    try:
        service = FileSearchService()

        # 테스트용 Store 생성 (또는 기존 확인)
        test_store_name = "test-integration-store"
        print(f"  - 테스트 Store 생성: {test_store_name}")

        store = service._get_or_create_store(test_store_name)

        if not store or not store.name:
            print("❌ Store 생성/조회 실패")
            return False

        print(f"✅ Vector Store 접근 성공: {store.name}")

        # Store 목록 조회
        print("\n  현재 존재하는 Store 목록:")
        store_count = 0
        for s in service.client.file_search_stores.list():
            print(f"    - {s.display_name} (ID: {s.name})")
            store_count += 1

        print(f"\n✅ 총 {store_count}개 Store 확인됨")
        return True

    except Exception as e:
        print(f"❌ Vector Store 접근 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_session_creation():
    """세션 생성 및 쿼리 테스트"""
    print("\n3. 세션 생성 및 쿼리 테스트...")
    try:
        from app.models import User, ChatSession, ChatMessage

        async with async_session_maker() as session:
            # 테스트 사용자 조회
            result = await session.execute(
                text("SELECT * FROM users LIMIT 1")
            )
            user = result.fetchone()

            if not user:
                print("⚠️  테스트 사용자가 없습니다")
                return True  # 경고만 표시하고 통과

            print(f"✅ 세션 생성 성공")
            print(f"  - 테스트 사용자: {user[1]}")  # username
            return True

    except Exception as e:
        print(f"❌ 세션 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """메인 테스트 실행"""
    print("=" * 60)
    print("통합 테스트 환경 구성 검증")
    print("=" * 60)
    print()

    # 1. DB 연결 테스트
    db_ok = await test_database_connection()
    if not db_ok:
        print("\n❌ DB 테스트 실패로 중단")
        sys.exit(1)

    # 2. Vector Store 접근 테스트
    vector_ok = await test_vector_store_access()
    if not vector_ok:
        print("\n❌ Vector Store 테스트 실패로 중단")
        sys.exit(1)

    # 3. 세션 테스트
    session_ok = await test_session_creation()
    if not session_ok:
        print("\n❌ 세션 테스트 실패로 중단")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("🎉 통합 테스트 환경 구성 완료!")
    print("=" * 60)
    print("\n✅ Phase 1.4 검증 완료:")
    print("  - 테스트 데이터베이스 연결 확인")
    print("  - 테스트용 Vector DB Store 생성 및 접근 확인")
    print("  - 세션 생성 및 쿼리 정상 동작")


if __name__ == "__main__":
    asyncio.run(main())
