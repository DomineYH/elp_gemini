# 롤백 절차서

## 문서 정보
- **작성일**: 2025-11-22
- **버전**: 2.0
- **대상**: DevOps, Backend 개발자, 운영팀
- **목적**: 배포 실패 시 신속한 복구

---

## 1. 롤백 개요

### 1.1 롤백 정의
배포된 변경사항을 이전 안정 버전으로 되돌리는 작업

### 1.2 롤백 원칙
1. **신속성**: 서비스 중단 최소화
2. **안전성**: 데이터 손실 방지
3. **검증성**: 롤백 후 정상 동작 확인
4. **문서화**: 모든 롤백 기록 남김

---

## 2. 롤백 결정 기준

### 2.1 즉시 롤백 (Critical)
다음 상황 발생 시 즉시 롤백 실행:

- ❌ **서비스 완전 중단**: API 응답 없음
- ❌ **데이터 손실**: DB 데이터 유실 또는 손상
- ❌ **치명적 보안 취약점**: 긴급 보안 패치 필요
- ❌ **대규모 에러**: 에러율 >10%
- ❌ **성능 급격 저하**: 응답 시간 >10초

### 2.2 계획적 롤백 (High Priority)
다음 상황에서 30분 내 롤백 검토:

- ⚠️ **기능 장애**: 주요 기능 동작 불가
- ⚠️ **높은 에러율**: 에러율 5-10%
- ⚠️ **성능 저하**: 응답 시간 >5초
- ⚠️ **예상치 못한 동작**: 비즈니스 로직 오류

### 2.3 모니터링 후 결정 (Medium Priority)
다음 상황에서 2시간 모니터링 후 결정:

- 🔍 **부분적 기능 오류**: 일부 사용자만 영향
- 🔍 **경미한 성능 저하**: 응답 시간 2-5초
- 🔍 **낮은 에러율**: 에러율 1-5%

---

## 3. 롤백 전 체크리스트

### 3.1 상황 파악
```bash
# 1. 에러 로그 확인
tail -n 100 logs/error.log

# 2. 서비스 상태 확인
sudo systemctl status elp_gemini

# 3. 데이터베이스 상태 확인
sqlite3 data/app.db ".tables"

# 4. 디스크 공간 확인
df -h
```

### 3.2 롤백 결정
- [ ] 에러 원인 파악 완료
- [ ] 롤백 결정 승인 (운영팀/개발팀)
- [ ] 사용자 공지 준비
- [ ] 백업 파일 존재 확인
- [ ] 롤백 담당자 지정

---

## 4. Phase별 롤백 절차

### 4.1 Phase 4 롤백 (레거시 제거 단계)

**상황**: 레거시 코드 제거 후 문제 발생

**절차**:

**Step 1: 서비스 중단**
```bash
sudo systemctl stop elp_gemini
```

**Step 2: 코드 롤백**
```bash
cd /opt/elp_gemini
git log --oneline -5  # 커밋 히스토리 확인
git revert <commit-hash>  # 또는
git reset --hard <previous-commit>
```

**Step 3: 의존성 복원**
```bash
source .venv/bin/activate
uv sync
```

**Step 4: 서비스 재시작**
```bash
sudo systemctl start elp_gemini
sudo systemctl status elp_gemini
```

**Step 5: 검증**
```bash
curl http://localhost:8000/health
pytest tests/ -v
```

---

### 4.2 Phase 3 롤백 (데이터 마이그레이션 단계)

**상황**: 데이터 마이그레이션 후 데이터 무결성 문제

**절차**:

**Step 1: 긴급 서비스 중단**
```bash
sudo systemctl stop elp_gemini
```

**Step 2: DB 백업 복원**
```bash
cd /opt/elp_gemini

# 현재 DB 백업 (롤백 실패 대비)
cp data/app.db backup/db_before_rollback_$(date +%Y%m%d_%H%M%S).db

# 이전 백업 복원
cp backup/db_backup_YYYYMMDD_HHMMSS.db data/app.db
```

**Step 3: 파일 시스템 복원**
```bash
# 마이그레이션된 파일 삭제
rm -rf data/lessonplan/*
rm -rf data/analys/*

# 구 시스템 데이터 복원 (백업 존재 시)
# (Vector DB는 자동 재생성됨)
```

**Step 4: 코드 롤백**
```bash
git reset --hard <before-migration-commit>
uv sync
```

**Step 5: 서비스 재시작 및 검증**
```bash
sudo systemctl start elp_gemini

# DB 데이터 검증
sqlite3 data/app.db "SELECT COUNT(*) FROM qa_logs;"
sqlite3 data/app.db "SELECT COUNT(*) FROM documents;"
```

---

### 4.3 Phase 2 롤백 (서비스 레이어 단계)

**상황**: 새로운 서비스 로직 오류

**절차**:

**Step 1: 서비스 중단**
```bash
sudo systemctl stop elp_gemini
```

**Step 2: 코드 롤백**
```bash
cd /opt/elp_gemini
git reset --hard <before-phase2-commit>
uv sync
```

**Step 3: 새 테이블 제거 (선택)**
```bash
# chat_sessions, chat_messages 테이블 삭제
python scripts/drop_new_tables.py
```

**Step 4: 서비스 재시작**
```bash
sudo systemctl start elp_gemini
```

---

### 4.4 Phase 1 롤백 (스키마 준비 단계)

**상황**: 새 테이블 구조 문제

**절차**:

**Step 1: 테이블 삭제**
```bash
cd /opt/elp_gemini
python scripts/drop_new_tables.py
```

**Step 2: 디렉토리 정리**
```bash
rm -rf data/lessonplan/*
rm -rf data/analys/*
rm -rf prompt/prompt.md
```

**Step 3: 코드 롤백**
```bash
git reset --hard <before-phase1-commit>
```

---

## 5. 긴급 전체 롤백

### 5.1 상황
모든 Phase 롤백 필요 (초기 상태로 복귀)

### 5.2 절차

**Step 1: 서비스 중단**
```bash
sudo systemctl stop elp_gemini
```

**Step 2: 완전 백업 (현재 상태 보존)**
```bash
cd /opt/elp_gemini
tar -czf /backup/elp_gemini_emergency_$(date +%Y%m%d_%H%M%S).tar.gz \
  data/ logs/ .env
```

**Step 3: DB 복원 (최초 백업)**
```bash
# 가장 오래된 안정 백업 사용
cp backup/db_backup_INITIAL.db data/app.db
```

**Step 4: 코드 복원 (최초 커밋)**
```bash
git fetch origin
git reset --hard origin/main  # 또는 특정 태그
uv sync
```

**Step 5: 환경 재설정**
```bash
# .env 확인
cat .env

# 디렉토리 정리
rm -rf data/lessonplan/*
rm -rf data/analys/*
```

**Step 6: 서비스 재시작**
```bash
sudo systemctl start elp_gemini
```

---

## 6. 롤백 후 검증

### 6.1 시스템 검증
```bash
# 1. 서비스 상태
sudo systemctl status elp_gemini

# 2. 헬스체크
curl http://localhost:8000/health

# 3. 로그 확인 (에러 없음)
tail -n 50 logs/error.log

# 4. 프로세스 확인
ps aux | grep gunicorn
```

### 6.2 기능 검증
```bash
# 통합 테스트 실행
pytest tests/test_integration*.py -v

# API 수동 테스트
# - 로그인
# - 지도안 업로드
# - QnA 세션 생성 및 질문
# - 평가 실행
```

### 6.3 데이터 검증
```bash
# DB 무결성 확인
sqlite3 data/app.db "PRAGMA integrity_check;"

# 데이터 개수 확인
sqlite3 data/app.db "SELECT COUNT(*) FROM users;"
sqlite3 data/app.db "SELECT COUNT(*) FROM qa_logs;"  # 구 버전
sqlite3 data/app.db "SELECT COUNT(*) FROM chat_sessions;"  # 신 버전

# 파일 시스템 확인
ls -la data/lessonplan/
ls -la data/analys/
```

---

## 7. 롤백 실패 시 대응

### 7.1 롤백 실패 상황
- DB 백업 손상
- 코드 충돌로 롤백 불가
- 서비스 재시작 실패

### 7.2 비상 대응 절차

**Option 1: 클린 설치**
```bash
# 1. 완전 백업
tar -czf /backup/full_backup_$(date +%Y%m%d_%H%M%S).tar.gz \
  /opt/elp_gemini

# 2. 새로운 디렉토리에 클론
cd /opt
mv elp_gemini elp_gemini_failed
git clone <repository-url> elp_gemini
cd elp_gemini

# 3. 초기 설정
cp /opt/elp_gemini_failed/.env .env
cp /opt/elp_gemini_failed/backup/db_backup_INITIAL.db data/app.db

# 4. 설치 및 시작
uv venv && source .venv/bin/activate
uv sync
sudo systemctl start elp_gemini
```

**Option 2: 컨테이너 복구 (Docker 사용 시)**
```bash
# 1. 이전 이미지로 복구
docker stop elp_gemini
docker rm elp_gemini
docker run -d --name elp_gemini \
  -v /opt/data:/app/data \
  elp_gemini:stable

# 2. 검증
docker logs elp_gemini
curl http://localhost:8000/health
```

---

## 8. 롤백 후 보고

### 8.1 롤백 보고서 작성

**필수 항목**:
1. 롤백 일시 및 담당자
2. 롤백 사유 (에러 내용, 로그)
3. 롤백 대상 (Phase, 커밋 해시)
4. 롤백 절차 (실행 명령어)
5. 검증 결과
6. 데이터 손실 여부
7. 근본 원인 분석
8. 재발 방지 대책

### 8.2 보고서 템플릿
```markdown
# 롤백 보고서

## 기본 정보
- **일시**: 2025-11-22 10:00:00
- **담당자**: 홍길동
- **시스템**: Production

## 롤백 사유
- **문제**: API 응답 없음
- **에러**: [에러 내용]
- **영향 범위**: 전체 사용자

## 롤백 내역
- **대상 Phase**: Phase 4
- **이전 커밋**: abc1234
- **롤백 커밋**: def5678
- **데이터 백업**: db_backup_20251122_095959.db

## 검증 결과
- [x] 서비스 정상 동작
- [x] API 응답 정상
- [x] 데이터 무결성 확인
- [ ] 성능 정상 (모니터링 중)

## 데이터 손실
- 손실 여부: 없음
- 영향 받은 데이터: 없음

## 근본 원인
[원인 분석]

## 재발 방지
[대책]
```

---

## 9. 롤백 연습 (Drill)

### 9.1 정기 롤백 훈련
- **빈도**: 분기별 1회
- **대상**: Staging 환경
- **목적**: 롤백 절차 숙지

### 9.2 훈련 시나리오
1. Phase 3 데이터 마이그레이션 롤백
2. Phase 4 코드 롤백
3. 긴급 전체 롤백

---

## 10. 참조 문서

- **배포 가이드**: docs/DEPLOYMENT_GUIDE.md
- **API 문서**: docs/API_DOCUMENTATION.md
- **마이그레이션 계획**: modify/plan.md

---

**작성자**: Claude Code (기계사제)
**최종 수정**: 2025-11-22
**버전**: 2.0

*"롤백은 실패가 아니라, 시스템을 보호하는 성스러운 방어 의식이다."*
*"옴니시아의 뜻에 따라 기계령이 안식하길."*
