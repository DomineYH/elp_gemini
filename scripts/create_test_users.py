"""
통합 테스트용 사용자 생성 스크립트

테스트에 필요한 사용자 계정을 생성합니다:
- testuser (일반 사용자)
- admin (관리자)
"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import select
from app.db import get_async_session_context
from app.models.users import User


async def create_test_users():
    """테스트 사용자 생성"""
    print("🔧 테스트 사용자 생성 중...")

    async with get_async_session_context() as db:
        # 1. 일반 사용자 확인 및 생성
        result = await db.execute(
            select(User).where(User.username == "testuser")
        )
        testuser = result.scalar_one_or_none()

        if testuser:
            print("✅ testuser 이미 존재")
        else:
            testuser = User(
                username="testuser",
                is_admin=False
            )
            testuser.set_password("testpassword")
            db.add(testuser)
            await db.commit()
            print("✅ testuser 생성 완료")

        # 2. 관리자 확인 및 생성
        result = await db.execute(
            select(User).where(User.username == "admin")
        )
        admin = result.scalar_one_or_none()

        if admin:
            print("✅ admin 이미 존재")
            # 관리자 권한 확인 및 업데이트
            if not admin.is_admin:
                admin.is_admin = True
                await db.commit()
                print("   관리자 권한 업데이트")
        else:
            admin = User(
                username="admin",
                is_admin=True
            )
            admin.set_password("admin1234")
            db.add(admin)
            await db.commit()
            print("✅ admin 생성 완료")

    print("\n" + "=" * 50)
    print("테스트 사용자 생성 완료")
    print("=" * 50)
    print("\n테스트 계정:")
    print("1. 일반 사용자")
    print("   - username: testuser")
    print("   - password: testpassword")
    print("   - is_admin: False")
    print("\n2. 관리자")
    print("   - username: admin")
    print("   - password: admin1234")
    print("   - is_admin: True")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(create_test_users())
