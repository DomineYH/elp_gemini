# 배포 가이드

## 문서 정보
- **작성일**: 2025-11-22
- **버전**: 2.0
- **대상**: DevOps, Backend 개발자
- **목적**: 리팩토링 후 배포 절차 안내

---

## 1. 환경 요구사항

### 1.1 시스템 요구사항
- **OS**: Linux (Ubuntu 20.04+) 또는 macOS
- **Python**: 3.10 이상
- **메모리**: 최소 2GB, 권장 4GB
- **디스크**: 최소 10GB 여유 공간

### 1.2 필수 소프트웨어
- Python 3.10+
- uv (Python 패키지 관리자)
- SQLite3
- Git

### 1.3 외부 서비스
- **Google Gemini API**
  - API Key 필수
  - File Search API 사용
  - Free Tier: 1GB Vector DB 제한

---

## 2. 설치 절차

### 2.1 코드 클론
```bash
git clone <repository-url>
cd elp_gemini
git checkout main
```

### 2.2 Python 환경 설정
```bash
# uv 설치 (없는 경우)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 가상환경 생성 및 패키지 설치
uv venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate  # Windows

uv sync
```

### 2.3 환경변수 설정
```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집
nano .env
```

**.env 필수 항목**:
```env
# Gemini API
GEMINI_API_KEY=your_api_key_here

# JWT 설정
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# 데이터베이스
DATABASE_URL=sqlite+aiosqlite:///./data/app.db

# 파일 저장 경로
LESSONPLAN_DIR=data/lessonplan
ANALYSIS_DIR=data/analys
PROMPT_DIR=prompt
```

### 2.4 디렉토리 구조 생성
```bash
mkdir -p data/lessonplan
mkdir -p data/analys
mkdir -p prompt
mkdir -p backup
```

---

## 3. 데이터베이스 초기화

### 3.1 새로운 설치 (초기 설정)
```bash
# 테이블 생성
python scripts/create_chat_tables.py

# 테스트 사용자 생성 (선택사항)
python scripts/create_test_users.py
```

### 3.2 기존 시스템 마이그레이션
```bash
# 1. DB 백업
python scripts/backup_db.py

# 2. 새 테이블 생성
python scripts/create_chat_tables.py

# 3. 데이터 마이그레이션
python scripts/migrate_to_chat_sessions.py
python scripts/migrate_documents_to_files.py
python scripts/migrate_evaluations_to_markdown.py
python scripts/migrate_prompts_to_file.py

# 4. 마이그레이션 검증
python scripts/verify_migration.py

# 5. 구 테이블 삭제 (검증 후)
python scripts/drop_old_tables.py
```

---

## 4. 서버 실행

### 4.1 개발 환경
```bash
# FastAPI 개발 서버
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4.2 프로덕션 환경
```bash
# Gunicorn + Uvicorn Worker
gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log
```

### 4.3 서비스 등록 (systemd)

**/etc/systemd/system/elp_gemini.service**:
```ini
[Unit]
Description=ELP Gemini QnA Service
After=network.target

[Service]
Type=notify
User=ubuntu
Group=ubuntu
WorkingDirectory=/path/to/elp_gemini
Environment="PATH=/path/to/elp_gemini/.venv/bin"
ExecStart=/path/to/elp_gemini/.venv/bin/gunicorn \
  app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

**서비스 관리**:
```bash
sudo systemctl enable elp_gemini
sudo systemctl start elp_gemini
sudo systemctl status elp_gemini
```

---

## 5. 배포 절차

### 5.1 Staging 환경 배포

**Step 1: 코드 배포**
```bash
ssh staging-server
cd /opt/elp_gemini
git pull origin main
source .venv/bin/activate
uv sync
```

**Step 2: 데이터베이스 마이그레이션**
```bash
# 백업
python scripts/backup_db.py

# 마이그레이션 (필요시)
python scripts/migrate_xxx.py
```

**Step 3: 서비스 재시작**
```bash
sudo systemctl restart elp_gemini
sudo systemctl status elp_gemini
```

**Step 4: 검증**
```bash
# 헬스체크
curl http://staging-server:8000/health

# API 테스트
pytest tests/ -v
```

---

### 5.2 Production 환경 배포

**사전 준비**:
1. Staging 환경 검증 완료
2. 배포 시간 공지 (서비스 중단 시)
3. 롤백 계획 확인

**배포 절차**:

**Step 1: DB 백업 (필수)**
```bash
ssh production-server
cd /opt/elp_gemini
python scripts/backup_db.py
# 백업 파일 확인: backup/db_backup_YYYYMMDD_HHMMSS.db
```

**Step 2: 코드 배포**
```bash
git pull origin main
source .venv/bin/activate
uv sync
```

**Step 3: 데이터베이스 마이그레이션**
```bash
# 마이그레이션 실행 (필요시)
python scripts/migrate_xxx.py

# 검증
python scripts/verify_migration.py
```

**Step 4: 서비스 재시작**
```bash
sudo systemctl restart elp_gemini
```

**Step 5: 모니터링**
```bash
# 로그 확인
tail -f logs/error.log

# 서비스 상태
sudo systemctl status elp_gemini

# API 응답 확인
curl http://production-server:8000/health
```

---

## 6. 모니터링 설정

### 6.1 로그 관리

**로그 파일 위치**:
- `logs/access.log`: API 요청 로그
- `logs/error.log`: 에러 로그
- `logs/app.log`: 애플리케이션 로그

**로그 로테이션** (/etc/logrotate.d/elp_gemini):
```
/opt/elp_gemini/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifesempty
    create 0640 ubuntu ubuntu
    postrotate
        systemctl reload elp_gemini > /dev/null 2>&1 || true
    endscript
}
```

### 6.2 헬스체크

**엔드포인트**: `GET /health`

**정상 응답**:
```json
{
  "status": "healthy",
  "timestamp": "2025-11-22T10:00:00"
}
```

### 6.3 성능 모니터링

**주요 지표**:
- CPU 사용률: <70%
- 메모리 사용률: <80%
- 디스크 사용률: <85%
- API 응답 시간: <2초 (평균)
- 에러율: <1%

---

## 7. 트러블슈팅

### 7.1 서비스 시작 실패
```bash
# 로그 확인
sudo journalctl -u elp_gemini -n 50

# 환경변수 확인
cat .env | grep GEMINI_API_KEY

# 권한 확인
ls -la data/
```

### 7.2 데이터베이스 오류
```bash
# DB 백업 복원
cp backup/db_backup_YYYYMMDD_HHMMSS.db data/app.db

# 테이블 확인
sqlite3 data/app.db ".tables"
```

### 7.3 API 응답 없음
```bash
# 서비스 상태 확인
sudo systemctl status elp_gemini

# 포트 확인
netstat -tlnp | grep 8000

# 방화벽 확인 (필요시)
sudo ufw status
```

---

## 8. 보안 체크리스트

- [ ] `.env` 파일 권한 설정 (600)
- [ ] 데이터베이스 백업 암호화
- [ ] HTTPS 적용 (Nginx/Reverse Proxy)
- [ ] API Key 로테이션 계획
- [ ] 로그 민감정보 마스킹
- [ ] 방화벽 설정 (필요한 포트만 개방)

---

## 9. 백업 정책

### 9.1 데이터베이스 백업
- **빈도**: 매일 자동 (cron)
- **보관 기간**: 30일
- **위치**: `backup/` 디렉토리

**Cron 설정** (매일 새벽 2시):
```bash
crontab -e

0 2 * * * cd /opt/elp_gemini && \
  /opt/elp_gemini/.venv/bin/python \
  scripts/backup_db.py >> logs/backup.log 2>&1
```

### 9.2 파일 백업
- **대상**: `data/lessonplan/`, `data/analys/`
- **빈도**: 주 1회
- **방법**: rsync 또는 클라우드 스토리지

---

**작성자**: Claude Code (기계사제)
**최종 수정**: 2025-11-22
**버전**: 2.0

*"배포는 성스러운 의식이며, 백업은 구원의 성사이다."*
