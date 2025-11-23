# 통합 테스트 가이드

## 목차
1. [개요](#개요)
2. [사전 준비](#사전-준비)
3. [테스트 실행](#테스트-실행)
4. [시나리오별 상세 설명](#시나리오별-상세-설명)
5. [문제 해결](#문제-해결)

---

## 개요

이 문서는 QnA 챗봇 애플리케이션의 통합 테스트를 실행하기 위한
가이드입니다.

### 테스트 시나리오
1. **시나리오 1**: 지도안 업로드 → QnA → 분석 → 결과 저장
2. **시나리오 2**: 평가기준 업로드 → 분석 → Store 삭제
3. **시나리오 3**: 세션 종료 → 임시 지도안 삭제
4. **시나리오 4**: 프롬프트 로드 → QnA

---

## 사전 준비

### 1. 환경 설정

#### 1.1 Python 패키지 설치
```bash
pip install httpx pytest
```

#### 1.2 환경 변수 설정
`.env` 파일에 다음 설정이 있는지 확인:
```bash
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
SECRET_KEY=your_secret_key
```

### 2. 데이터베이스 준비

#### 2.1 테스트 사용자 생성
```bash
# 테스트 사용자 생성 스크립트 실행
python scripts/create_test_users.py
```

생성될 사용자:
- **일반 사용자**: username=`testuser`, password=`testpassword`
- **관리자**: username=`admin`, password=`adminpassword`

#### 2.2 프롬프트 파일 확인
`prompt/prompt.md` 파일이 존재하는지 확인:
```bash
ls -l prompt/prompt.md
```

없으면 생성:
```bash
mkdir -p prompt
cat > prompt/prompt.md <<EOF
# qna

당신은 지도안 분석 전문가입니다.
사용자의 질문에 대해 지도안 내용을 바탕으로 답변하세요.

# evaluation

당신은 교육 전문가입니다.
제공된 평가기준을 바탕으로 지도안을 평가하세요.
EOF
```

### 3. 서버 실행

#### 3.1 서버 시작
```bash
# 터미널 1에서 서버 실행
cd /path/to/elp_gemini
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 3.2 서버 확인
```bash
# 터미널 2에서 확인
curl http://localhost:8000/health
```

예상 출력:
```json
{"status": "healthy"}
```

---

## 테스트 실행

### 방법 1: 전체 테스트 실행 (권장)

```bash
cd tests
python run_all_integration_tests.py
```

### 방법 2: 개별 시나리오 실행

#### 시나리오 1
```bash
python tests/test_integration_scenario_1.py
```

#### 시나리오 2
```bash
python tests/test_integration_scenario_2.py
```

#### 시나리오 3
```bash
python tests/test_integration_scenario_3.py
```

#### 시나리오 4
```bash
python tests/test_integration_scenario_4.py
```

### 테스트 결과 확인

#### 콘솔 출력
실시간으로 테스트 진행 상황이 출력됩니다.

#### 리포트 파일
```bash
ls -lt tests/reports/
cat tests/reports/integration_test_report_*.md
```

---

## 시나리오별 상세 설명

### 시나리오 1: 지도안 업로드 → QnA → 분석 → 결과 저장

**목적**: 전체 플로우가 정상 동작하는지 확인

**절차**:
1. 테스트 지도안 파일 업로드
2. QnA 세션 생성
3. 질문 2회 수행
4. 평가 실행
5. 평가 결과 조회

**검증 항목**:
- ✅ 지도안이 정상 업로드됨
- ✅ QnA 세션이 생성됨
- ✅ 질문에 대한 답변이 생성됨
- ✅ 평가가 실행되고 결과가 저장됨
- ✅ 평가 결과를 조회할 수 있음

### 시나리오 2: 평가기준 업로드 → 분석 → Store 삭제

**목적**: 평가기준 관리 기능 확인

**절차**:
1. 첫 번째 평가기준 업로드
2. 두 번째 평가기준 업로드 (첫 번째 자동 삭제)
3. 평가기준 전체 삭제
4. 삭제 확인 (평가 시도 → 실패)

**검증 항목**:
- ✅ 평가기준이 정상 업로드됨
- ✅ 새 업로드 시 기존 평가기준이 자동 삭제됨
- ✅ 전체 삭제 시 Store가 재생성됨
- ✅ 삭제 후 평가가 실패함

### 시나리오 3: 세션 종료 → 임시 지도안 삭제

**목적**: Vector Store 임시 저장 및 삭제 확인

**절차**:
1. 지도안 임시 업로드
2. QnA 세션 생성
3. 질문 수행
4. 세션 종료 (Store 삭제)
5. 삭제 확인 (QnA 재시도 → 실패)

**검증 항목**:
- ✅ 지도안이 Vector Store에 임시 업로드됨
- ✅ QnA가 정상 동작함
- ✅ 세션 종료 시 Store가 삭제됨
- ✅ 삭제 후 QnA가 실패함

**주의사항**:
- 세션 종료 API가 구현되지 않았을 경우,
  `LessonPlanVectorService.delete_on_session_close()`
  수동 호출 필요

### 시나리오 4: 프롬프트 로드 → QnA

**목적**: 프롬프트 시스템 정상 동작 확인

**절차**:
1. 프롬프트 파일 존재 확인
2. 지도안 업로드
3. QnA 세션 생성
4. 다양한 질문 4회 수행
5. 응답에서 프롬프트 적용 분석

**검증 항목**:
- ✅ `prompt/prompt.md` 파일이 존재함
- ✅ QnA 프롬프트가 로드됨
- ✅ 질문에 대한 답변이 생성됨
- ✅ 프롬프트가 답변에 적용됨

---

## 문제 해결

### 1. 서버 연결 실패

**증상**:
```
❌ 테스트 실패: Connection refused
```

**해결**:
1. 서버가 실행 중인지 확인
2. 포트 번호 확인 (8000)
3. 방화벽 설정 확인

### 2. 인증 실패

**증상**:
```
❌ 로그인 실패: 401 Unauthorized
```

**해결**:
1. 테스트 사용자가 생성되었는지 확인:
   ```bash
   sqlite3 data/app.db "SELECT username FROM users;"
   ```
2. 사용자가 없으면 생성:
   ```bash
   python scripts/create_test_users.py
   ```

### 3. 평가기준 업로드 실패

**증상**:
```
❌ 평가기준 업로드 실패: 403 Forbidden
```

**해결**:
1. 관리자 권한 확인
2. 관리자 계정으로 로그인했는지 확인
3. `admin` 사용자가 `is_admin=True`인지 확인:
   ```bash
   sqlite3 data/app.db "SELECT username, is_admin FROM users WHERE username='admin';"
   ```

### 4. Vector Store 오류

**증상**:
```
❌ Vector Store 접근 실패
```

**해결**:
1. Gemini API 키 확인:
   ```bash
   echo $GEMINI_API_KEY
   ```
2. API 키가 유효한지 확인
3. Free Tier 제한 확인 (1GB)

### 5. 프롬프트 파일 없음

**증상**:
```
❌ 프롬프트 파일 없음: prompt/prompt.md
```

**해결**:
1. 파일 생성:
   ```bash
   mkdir -p prompt
   cp prompt_template.md prompt/prompt.md
   ```
2. 또는 수동으로 작성

---

## 테스트 결과 해석

### 성공 케이스

```
========================================
✅ 통합 테스트 시나리오 1 완료
========================================

결과 요약:
- 지도안: testuser_test_lessonplan.txt
- QnA 세션: 123
- 질문 수: 2개
- 평가 결과: testuser_test_lessonplan.txt.md
- 결과 크기: 1234 bytes
```

### 실패 케이스

```
❌ 테스트 실패: 평가 실행 중 오류가 발생했습니다.
```

**대응**:
1. 에러 메시지 확인
2. 서버 로그 확인:
   ```bash
   tail -f app.log
   ```
3. 해당 단계 재시도
4. 필요 시 개발자에게 문의

---

## 추가 정보

### 테스트 데이터 정리

```bash
# 테스트 데이터 삭제
rm -rf data/lessonplan/testuser_*
rm -rf data/analys/testuser_*

# DB 초기화 (선택)
rm data/app.db
python scripts/create_chat_tables.py
python scripts/create_test_users.py
```

### 로그 확인

```bash
# 애플리케이션 로그
tail -f app.log

# 테스트 로그
tail -f tests/test.log
```

---

**작성자**: Claude Code
**작성일**: 2025-11-21
**버전**: 1.0
