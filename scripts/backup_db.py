"""
데이터베이스 백업 스크립트
SQLite 데이터베이스를 백업합니다
"""
import shutil
from datetime import datetime
from pathlib import Path


def backup_database(
    db_path: str = "./data/app.db",
    backup_dir: str = "./data/backups",
):
    """
    데이터베이스 백업 수행

    Args:
        db_path: 원본 데이터베이스 경로
        backup_dir: 백업 저장 디렉토리
    """
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"데이터베이스 파일을 찾을 수 없습니다: {db_path}")
        return

    # 백업 디렉토리 생성
    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    # 백업 파일명 생성 (타임스탬프 포함)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_path / f"app_backup_{timestamp}.db"

    # 백업 수행
    try:
        shutil.copy2(db_file, backup_file)
        print(f"백업 완료: {backup_file}")
        print(f"파일 크기: {backup_file.stat().st_size / 1024:.2f} KB")

        # 오래된 백업 정리 (최근 10개만 유지)
        backups = sorted(backup_path.glob("app_backup_*.db"))
        if len(backups) > 10:
            for old_backup in backups[:-10]:
                old_backup.unlink()
                print(f"오래된 백업 삭제: {old_backup.name}")

    except Exception as e:
        print(f"백업 실패: {str(e)}")


if __name__ == "__main__":
    backup_database()
