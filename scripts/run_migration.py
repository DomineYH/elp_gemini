#!/usr/bin/env python3
"""
DB 마이그레이션 실행 스크립트
- SQLite DB에 마이그레이션 SQL 파일 적용
- 트랜잭션 기반 안전한 마이그레이션
"""
import sqlite3
import sys
from pathlib import Path
from datetime import datetime


def get_db_path() -> Path:
    """데이터베이스 파일 경로 반환"""
    # 프로젝트 루트 경로
    root = Path(__file__).parent.parent
    db_path = root / "data" / "app.db"

    # data 디렉터리가 없으면 생성
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return db_path


def get_migration_files() -> list[Path]:
    """마이그레이션 파일 목록 반환 (번호순 정렬)"""
    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        raise FileNotFoundError(
            f"마이그레이션 디렉터리 없음: {migrations_dir}"
        )

    # .sql 파일만 선택하고 이름순 정렬
    sql_files = sorted(migrations_dir.glob("*.sql"))

    if not sql_files:
        raise FileNotFoundError(
            f"마이그레이션 파일 없음: {migrations_dir}"
        )

    return sql_files


def run_migration(
    db_path: Path, migration_file: Path
) -> None:
    """
    단일 마이그레이션 파일 실행

    Args:
        db_path: 데이터베이스 파일 경로
        migration_file: 마이그레이션 SQL 파일 경로

    Raises:
        sqlite3.Error: SQL 실행 오류
    """
    print(f"[마이그레이션] {migration_file.name} 실행 중...")

    # SQL 파일 읽기
    sql_content = migration_file.read_text(encoding="utf-8")

    # DB 연결 및 실행
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        # 트랜잭션 시작
        cursor.execute("BEGIN TRANSACTION")

        # SQL 실행 (여러 문장을 executescript로 실행)
        cursor.executescript(sql_content)

        # 커밋
        conn.commit()
        print(f"[완료] {migration_file.name}")

    except sqlite3.Error as e:
        # 롤백
        conn.rollback()
        print(f"[실패] {migration_file.name}: {e}")
        raise

    finally:
        conn.close()


def create_migration_log_table(db_path: Path) -> None:
    """
    마이그레이션 로그 테이블 생성
    실행된 마이그레이션 추적용
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS migration_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_file TEXT NOT NULL UNIQUE,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


def is_migration_applied(
    db_path: Path, migration_file: Path
) -> bool:
    """마이그레이션이 이미 적용되었는지 확인"""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM migration_logs WHERE migration_file = ?",
            (migration_file.name,)
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def log_migration(db_path: Path, migration_file: Path) -> None:
    """마이그레이션 적용 로그 기록"""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO migration_logs (migration_file) VALUES (?)",
            (migration_file.name,)
        )
        conn.commit()
    finally:
        conn.close()


def main():
    """메인 실행 함수"""
    print("=" * 60)
    print("DB 마이그레이션 시작")
    print(f"실행 시각: {datetime.now()}")
    print("=" * 60)

    try:
        # DB 경로 가져오기
        db_path = get_db_path()
        print(f"DB 경로: {db_path}")

        # 마이그레이션 로그 테이블 생성
        create_migration_log_table(db_path)

        # 마이그레이션 파일 목록
        migration_files = get_migration_files()
        print(f"발견된 마이그레이션: {len(migration_files)}개")

        # 각 마이그레이션 실행
        applied_count = 0
        for mig_file in migration_files:
            # 이미 적용된 마이그레이션은 스킵
            if is_migration_applied(db_path, mig_file):
                print(f"[스킵] {mig_file.name} (이미 적용됨)")
                continue

            # 마이그레이션 실행
            run_migration(db_path, mig_file)

            # 로그 기록
            log_migration(db_path, mig_file)

            applied_count += 1

        print("=" * 60)
        print(f"마이그레이션 완료: {applied_count}개 적용됨")
        print("=" * 60)

    except Exception as e:
        print(f"\n[오류] 마이그레이션 실패: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
