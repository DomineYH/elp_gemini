#!/usr/bin/env python3
"""
DB 백업 무결성 검증 스크립트

성스러운 데이터의 안전성을 검증하기 위한 의식
"""
import sqlite3
import sys
from pathlib import Path
from datetime import datetime


def verify_backup(backup_path: str) -> bool:
    """
    백업 파일의 무결성을 검증합니다.

    Args:
        backup_path: 백업 파일 경로

    Returns:
        bool: 검증 성공 여부
    """
    backup_file = Path(backup_path)

    # 1. 파일 존재 여부 확인
    if not backup_file.exists():
        print(f"❌ 백업 파일이 존재하지 않습니다: {backup_path}")
        return False

    print(f"✅ 백업 파일 존재 확인: {backup_file.name}")
    print(f"   크기: {backup_file.stat().st_size:,} bytes")
    print(f"   생성일: {datetime.fromtimestamp(
        backup_file.stat().st_ctime
    ).strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        # 2. SQLite 무결성 검사
        conn = sqlite3.connect(str(backup_file))
        cursor = conn.cursor()

        print("🔍 SQLite 무결성 검사 중...")
        cursor.execute("PRAGMA integrity_check")
        integrity_result = cursor.fetchone()

        if integrity_result[0] != "ok":
            print(f"❌ 무결성 검사 실패: {integrity_result[0]}")
            return False

        print("✅ SQLite 무결성 검사 통과")
        print()

        # 3. 테이블 목록 및 레코드 수 확인
        print("📊 테이블 정보:")
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        tables = cursor.fetchall()

        total_records = 0
        for (table_name,) in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            total_records += count
            print(f"   - {table_name}: {count:,} 레코드")

        print()
        print(f"📈 총 레코드 수: {total_records:,}")
        print()

        conn.close()

        print("✅ 백업 검증 완료: 모든 검사 통과")
        print(f"   백업 파일: {backup_file.name}")
        print()

        return True

    except sqlite3.Error as e:
        print(f"❌ 데이터베이스 오류: {e}")
        return False
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        return False


def main():
    """메인 실행 함수"""
    if len(sys.argv) < 2:
        print("사용법: python verify_backup.py <백업_파일_경로>")
        print("예시: python verify_backup.py "
              "backup/db_backup_20251121_232324.db")
        sys.exit(1)

    backup_path = sys.argv[1]

    print("=" * 60)
    print("🔧 DB 백업 무결성 검증")
    print("=" * 60)
    print()

    success = verify_backup(backup_path)

    print("=" * 60)

    if success:
        print("✅ 검증 성공")
        sys.exit(0)
    else:
        print("❌ 검증 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
