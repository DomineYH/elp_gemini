"""
채팅 테이블 생성 스크립트
chat_sessions, chat_messages 테이블 생성
"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import Base, engine
from app.models import ChatSession, ChatMessage


async def create_tables():
    """채팅 관련 테이블 생성"""
    print("채팅 테이블 생성 시작...")

    async with engine.begin() as conn:
        # 새 테이블만 생성 (기존 테이블은 유지)
        await conn.run_sync(Base.metadata.create_all)

    print("✅ 채팅 테이블 생성 완료:")
    print("  - chat_sessions")
    print("  - chat_messages")


async def verify_tables():
    """테이블 생성 검증"""
    from sqlalchemy import text

    print("\n테이블 검증 중...")

    async with engine.connect() as conn:
        # SQLite 테이블 목록 조회
        result = await conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' "
                "ORDER BY name"
            )
        )
        tables = [row[0] for row in result]

        print("\n현재 데이터베이스 테이블:")
        for table in tables:
            print(f"  - {table}")

        # 필수 테이블 확인
        required = ["chat_sessions", "chat_messages"]
        missing = [t for t in required if t not in tables]

        if missing:
            print(f"\n❌ 누락된 테이블: {missing}")
            return False

        print("\n✅ 모든 필수 테이블 확인됨")
        return True


async def main():
    """메인 실행 함수"""
    try:
        await create_tables()
        success = await verify_tables()

        if success:
            print("\n🎉 마이그레이션 성공!")
        else:
            print("\n⚠️ 마이그레이션 검증 실패")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
