#!/bin/bash
# 데이터베이스 리셋 스크립트
# 기존 데이터베이스를 백업하고 새로 생성합니다.

set -e  # 에러 발생 시 중단

echo "=========================================="
echo "데이터베이스 리셋"
echo "=========================================="

# 데이터베이스 디렉토리
DB_DIR="./data"
DB_FILE="$DB_DIR/app.db"

# 백업 생성
if [ -f "$DB_FILE" ]; then
    BACKUP_NAME="app.db.backup.$(date +%Y%m%d_%H%M%S)"
    echo "✓ 기존 데이터베이스 백업: $BACKUP_NAME"
    cp "$DB_FILE" "$DB_DIR/$BACKUP_NAME"

    # WAL 파일도 백업
    if [ -f "$DB_FILE-wal" ]; then
        cp "$DB_FILE-wal" "$DB_DIR/$BACKUP_NAME-wal"
    fi
    if [ -f "$DB_FILE-shm" ]; then
        cp "$DB_FILE-shm" "$DB_DIR/$BACKUP_NAME-shm"
    fi
fi

# 기존 데이터베이스 삭제
echo "✓ 기존 데이터베이스 삭제"
rm -f "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-shm"

echo "✓ 완료!"
echo ""
echo "이제 애플리케이션을 시작하면 새 스키마로 데이터베이스가 생성됩니다:"
echo "  python -m uvicorn app.main:app --reload"
echo ""
echo "관리자 계정: admin / admin"
echo "=========================================="
