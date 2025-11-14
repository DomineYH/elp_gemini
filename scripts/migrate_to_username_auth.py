"""
데이터베이스 마이그레이션: email/password 인증 → username/nickname 인증
기존 데이터를 백업하고 새 스키마로 데이터베이스를 재생성합니다.
"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.db import engine, init_db
from app.config import settings
import shutil
from datetime import datetime


async def migrate():
    """데이터베이스 마이그레이션 실행"""

    # 데이터베이스 파일 경로
    db_path = Path("./data/app.db")

    print("=" * 60)
    print("데이터베이스 마이그레이션: username/nickname 인증 시스템")
    print("=" * 60)

    # 1. 기존 데이터베이스 백업
    if db_path.exists():
        backup_name = f"app.db.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = db_path.parent / backup_name

        print(f"\n✓ 기존 데이터베이스 백업 중...")
        shutil.copy2(db_path, backup_path)
        print(f"  백업 완료: {backup_path}")

        # WAL 파일도 백업
        wal_files = [db_path.parent / f"{db_path.name}-wal",
                     db_path.parent / f"{db_path.name}-shm"]
        for wal_file in wal_files:
            if wal_file.exists():
                wal_backup = backup_path.parent / f"{backup_name}{wal_file.suffix}"
                shutil.copy2(wal_file, wal_backup)
                print(f"  백업 완료: {wal_backup}")

    # 2. 기존 데이터베이스 삭제
    print(f"\n✓ 기존 데이터베이스 삭제 중...")
    if db_path.exists():
        db_path.unlink()
        print(f"  삭제 완료: {db_path}")

    # WAL 파일도 삭제
    wal_files = [db_path.parent / f"{db_path.name}-wal",
                 db_path.parent / f"{db_path.name}-shm"]
    for wal_file in wal_files:
        if wal_file.exists():
            wal_file.unlink()
            print(f"  삭제 완료: {wal_file}")

    # 3. 새 스키마로 데이터베이스 생성
    print(f"\n✓ 새 스키마로 데이터베이스 생성 중...")
    await init_db()
    print(f"  생성 완료: {db_path}")

    # 4. 마이그레이션 완료
    print("\n" + "=" * 60)
    print("✓ 마이그레이션 완료!")
    print("=" * 60)
    print("\n새로운 인증 시스템:")
    print("  - 사용자 ID: username 필드 사용")
    print("  - 인증 방식: username + nickname 매칭")
    print("  - 관리자 계정: admin / admin")
    print("\n애플리케이션을 시작하세요:")
    print("  python -m uvicorn app.main:app --reload")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate())
