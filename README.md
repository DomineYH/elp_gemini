# AI-Based Lesson Design Feedback System (AI기반 수업설계 피드백 시스템)

Python 3.10+ FastAPI 기반 AI 수업설계 피드백 시스템

## 주요 기능

### MVP 핵심 기능
- **문서 QnA**: PDF 업로드 후 Google Gemini API를 통한 RAG 기반 질문답변
- **자동 평가**: 루브릭 기반 문서 자동 평가 및 보고서 생성
- **사용자 인증**: 세션 기반 로그인/로그아웃, 사용자별 데이터 격리
- **문서 관리**: 문서 업로드, 조회, 삭제, 상태 필터링, 검색
- **관리자 대시보드**: 사용자 관리, QnA 로그, 시스템 프롬프트 관리

### 기술 스택
- **Backend**: FastAPI (async), SQLAlchemy (async), SQLite (WAL mode)
- **LLM**: Google Gemini API (gemini-3.1-flash-lite)
- **RAG**: Google File Search Tool
- **Frontend**: Jinja2 Templates, Tailwind CSS (CDN)
- **Auth**: Session-based with bcrypt

## 빠른 시작

### 1. 환경 설정

```bash
# Python 3.10+ 필요
python --version

# 프로젝트 클론
git clone <repository-url>
cd elp_gemini

# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 의존성 설치
pip install -e .
```

### 2. 환경 변수 설정

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 수정
# GOOGLE_API_KEY: Google AI Studio에서 발급
# SECRET_KEY: openssl rand -hex 32
```

### 3. 데이터베이스 초기화 및 실행

```bash
# 서버 실행 (자동으로 DB 초기화)
python -m app.main

# 또는 uvicorn으로 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 접속

```
- 웹 UI: http://localhost:8000
- API 문서: http://localhost:8000/docs
- Health Check: http://localhost:8000/health
```

관리자 계정(ID `admin`)은 `admin` 계정이 없을 때 시작 시 한 번 만들어진다.
초기 비밀번호는 `.env`의 `ADMIN_INITIAL_PASSWORD`로 지정한다(8자 이상, 문자와 숫자 포함).
운영 모드(`DEBUG=false`)에서 이 값이 없으면 관리자 계정을 만들지 않는다.
로그인 후 관리자 메뉴의 **계정**(`/admin/account`)에서 비밀번호를 바꾼다.

## 프로젝트 구조

```
elp_gemini/
├── app/
│   ├── models/          # SQLAlchemy 모델
│   ├── schemas/         # Pydantic 스키마
│   ├── routers/         # FastAPI 라우터
│   ├── services/        # 비즈니스 로직
│   ├── templates/       # Jinja2 템플릿
│   ├── static/          # 정적 파일
│   ├── utils/           # 유틸리티
│   ├── config.py        # 설정
│   ├── db.py            # 데이터베이스
│   └── main.py          # 앱 엔트리포인트
├── data/                # 데이터베이스 및 업로드 파일
├── scripts/             # 유틸리티 스크립트
├── specs/               # 기능 명세서
├── pyproject.toml       # 프로젝트 설정
└── README.md
```

## 사용 가이드

### 일반 사용자

1. **로그인**: 사용자 ID와 비밀번호로 로그인
2. **문서 업로드**: PDF 파일 업로드 (최대 50MB)
3. **질문하기**: 업로드한 문서에 대해 질문
4. **평가 요청**: 관리자가 설정한 루브릭으로 문서 평가

### 관리자

1. **대시보드**: `/admin/dashboard` - 플랫폼 메트릭 확인
2. **사용자 관리**: `/admin/users` - 사용자 활동 모니터링
3. **QnA 로그**: `/admin/qna-logs` - 질문답변 기록 조회
4. **프롬프트 관리**: `/admin/prompts` - 시스템 프롬프트 버전 관리
5. **전체 내보내기**: `/admin/api/exports/all.zip` - ZIP 안의 `users.csv` 열은 `user_id, username, created_at, n_reports, n_sessions, n_lessonplans`(관리자 전용이라 username을 익명화하지 않음)

## 개발

### 코드 스타일

```bash
# Black 포매터 (80자 제한, pyproject.toml 설정)
black .

# Ruff 린터
ruff check .
```

### Tailwind CSS 재생성

화면은 CDN 대신 미리 빌드한 `app/static/css/tailwind.css`(커밋 대상)를 씁니다.
템플릿이나 `app/static/js/*.js`의 클래스를 바꾼 뒤에는 다시 빌드해 함께 커밋합니다.

```bash
# Tailwind v3.4.17 standalone CLI를 .cache/에 받아 sha256 검증 후 빌드 (Node 불필요)
scripts/build_tailwind.sh
```

### 데이터베이스 백업

```bash
python scripts/backup_db.py
```

프롬프트를 저장할 때마다 직전 `prompt/prompt.md`를 `prompt/prompt.md.bak-<UTC 시각>`으로 남기고 최신 10개만 유지한다. 복원은 원하는 백업을 `prompt/prompt.md`로 덮어쓴 뒤 서버를 재시작한다.

### 테스트

```bash
# 단위 테스트
pytest

# 커버리지
pytest --cov=app tests/

# git blame에서 전체 포맷 커밋 건너뛰기 (클론마다 한 번)
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

### CI (래칫)

`.github/workflows/ci.yml`이 main 대상 PR과 main push마다 세 가지를 검사합니다. 테스트는 기존 실패는 허용하고 새 실패만 막는 래칫 방식입니다.

1. 이모지 회귀 점검 (`scripts/check_no_emojis_in_reports.py`)
2. lint: 저장소 전체 `ruff check .` 위반 0건, `black --check .`(80자) 통과
3. 테스트 래칫: pytest 실패 집합이 `tests/known_failures.txt`와 다르면 실패 (새 실패 또는 목록에 있는데 통과한 항목)

로컬에서 같은 검사를 돌리려면 (`.env` 없이 CI와 같은 조건):

```bash
export GOOGLE_API_KEY=ci-placeholder \
  SECRET_KEY=ci-placeholder-secret-key-0123456789abcdef \
  SESSION_HTTPS_ONLY=false TZ=UTC
uv run --frozen python scripts/check_no_emojis_in_reports.py
uv run --frozen ruff check .
uv run --frozen black --check .
uv run --frozen python scripts/ci_ratchet.py tests
```

`tests/known_failures.txt`는 줄어들기만 해야 합니다. 테스트를 고쳐 CI가 `fixed`를 알리면 해당 줄을 지웁니다. 목록 전체를 다시 쓰려면 위 환경변수로 `uv run --frozen python scripts/ci_ratchet.py tests --update`를 실행합니다. 새 실패를 목록에 추가해서 CI를 통과시키지 않습니다.

커밋 전 ruff·black 검사와 이모지 점검은 pre-commit으로 돌릴 수 있습니다 (테스트는 CI만 돌립니다).

```bash
uv tool install pre-commit && pre-commit install
```

### 분석 보고서 이모지 회귀 점검

`prompt/prompt.md`의 `lesson_analysis` 섹션, `app/schemas/lessonplan_analysis.py`의 OpenAPI 예시, `app/static/reports/*_reports.md` 보고서에 이모지가 재유입되는 것을 차단합니다 (이슈 #31).

```bash
make check-emojis
# 또는 직접:
python3 scripts/check_no_emojis_in_reports.py
```

이모지가 발견되면 stderr 에 `파일:줄:컬럼:이모지` 를 출력하고 exit 1 로 종료합니다. 인용 블록(`>`)과 프롬프트의 부정 예시 가드 블록은 허용 영역으로 제외됩니다.

## 환경 변수

```bash
# 필수
GOOGLE_API_KEY=          # Google AI Studio API 키
SECRET_KEY=              # 세션 암호화 키 (32+ 문자)

# 선택
DEBUG=false              # 디버그 모드
DATABASE_URL=            # 데이터베이스 경로
MAX_UPLOAD_SIZE=52428800 # 최대 업로드 크기 (50MB)
UPLOAD_DIR=./data/uploads
GEMINI_QNA_MODEL=gemini-3.1-flash-lite   # QnA
GEMINI_EVAL_MODEL=gemini-3.1-flash-lite  # 지도안 분석(평가)
GEMINI_SIM_MODEL=gemini-3.1-flash-lite   # 수업 시뮬레이션
FS_MAIN_STORE_NAME=main-store
FS_RUBRIC_STORE_NAME=rubric-store
```

## 배포 / 보안 헤더

앱은 모든 응답에 다음 헤더를 붙입니다 (`app/middleware/security_headers.py`).

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy-Report-Only`: 템플릿의 인라인 스크립트를 걷어낼 때까지 차단 없이 위반만 보고하는 모드입니다.

HSTS(`Strict-Transport-Security`)는 앱이 보내지 않습니다. TLS를 종료하는 리버스 프록시에서 설정합니다. nginx 예:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

## 문제 해결

### 데이터베이스 초기화
```bash
rm data/app.db
python -m app.main
```

### 포트 충돌
```bash
# 다른 포트 사용
uvicorn app.main:app --port 8001
```

## 라이선스

MIT License

## 기여

PRs welcome! 이슈를 먼저 생성해주세요.

## QnA 시스템 아키텍처

### 이중 검색 시스템 (Dual Search System)

QnA 서비스는 Vector Search와 File Search를 결합한 이중 검색 시스템을 사용합니다.

#### 검색 시스템 구성

1. **Vector Search (평가기준 벡터 검색)**
   - 역할: 평가기준 관련 컨텍스트를 참고 자료로 제공
   - 구현: CriteriaVectorService
   - 출력: 프롬프트의 "참고 자료" 섹션

2. **File Search (문서 검색)**
   - 역할: 평가기준 문서 + 사용자 업로드 문서 검색
   - 구현: Gemini File Search API
   - 검색 대상:
     - `rubricstore`: 평가기준 문서 (모든 사용자 공유)
     - `user{id}store`: 사용자별 업로드 문서

#### 검색 흐름

```
사용자 질문
    │
    ├─→ Vector Search
    │   └─→ 평가기준 벡터 검색 → 참고 자료
    │
    └─→ File Search
        ├─→ rubricstore (평가기준 원본)
        └─→ user{id}store (사용자 문서)
            └─→ 문서 기반 답변

최종 답변 = Vector Search 컨텍스트 + File Search 결과
```

#### 주요 특징

- **Vector Search와 rubricstore의 관계**: 
  - Vector Search는 rubricstore 데이터를 벡터화하여 검색
  - File Search는 rubricstore 원본 문서를 직접 참조
  - 두 방식 모두 동일한 평가기준 데이터 활용

- **사용자별 문서 격리**: 
  - 각 사용자는 독립적인 File Search Store 보유
  - 평가기준은 모든 사용자가 공유

#### 관련 서비스

- `QnAService`: 이중 검색 시스템 통합 관리
- `CriteriaContextService`: Vector Search 처리
- `CriteriaVectorService`: 평가기준 벡터 검색
- `FileSearchService`: File Search Store 관리
