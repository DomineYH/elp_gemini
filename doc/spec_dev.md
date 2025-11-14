
# spec.md  
AI 기반 문서 평가·QnA 플랫폼 – 개발용 Technical Spec

> 이 문서는 **개발 관점**에서 필요한 스펙만 정리한 문서입니다.  
> 제품 개념/요구사항(PRD)은 별도 문서를 기준으로 합니다.

---

## 1. 전체 기술 스택 개요

### 1.1 런타임 & 언어

- 언어: **Python 3.10+**
- 실행 환경: 로컬 개발(uv 기반 venv) + 단일 서버 배포 가정

### 1.2 핵심 기술

- 웹 프레임워크: **FastAPI**
- 템플릿 엔진: **Jinja2**
- DB: **SQLite3** (파일 기반, 단일 인스턴스 기준)
- 패키지/환경 관리: **uv**
- 프론트엔드:
  - HTML5 + Jinja 템플릿
  - Tailwind CSS
  - Vanilla JS (필요 시 최소한의 스크립트)

### 1.3 LLM & RAG

- LLM 공급자: **Google Gemini API**
- 사용 모델:
  - `gemini-2.5-flash` → 문서 기반 QnA/챗봇
  - `gemini-2.5-pro` → 평가/피드백(보고서 생성)
- RAG:
  - Google **File Search Tool** 활용
  - File Search Store 구성:
    - `main-store` : 사용자 A 문서용
    - `rubric-store` : 평가 기준 B 문서용
  - 검색 시 메타데이터 필터:
    - `user_id`, `random_key` 기준으로 사용자·문서별 격리

---

## 2. 프로젝트 구조 (초안)

```text
project_root/
├─ app/
│  ├─ main.py               # FastAPI 엔트리포인트
│  ├─ config.py             # 설정, 환경변수 로딩
│  ├─ db.py                 # SQLite 연결, 세션 관리
│  ├─ models/               # ORM / DB 모델 정의
│  │  ├─ __init__.py
│  │  ├─ users.py
│  │  ├─ documents.py
│  │  ├─ prompts.py
│  │  ├─ evaluations.py
│  │  └─ qa_logs.py
│  ├─ routers/              # FastAPI 라우터
│  │  ├─ __init__.py
│  │  ├─ auth.py
│  │  ├─ user_docs.py
│  │  ├─ qna.py
│  │  ├─ eval.py
│  │  └─ admin.py
│  ├─ services/             # 비즈니스 로직
│  │  ├─ __init__.py
│  │  ├─ file_search_service.py
│  │  ├─ qna_service.py
│  │  ├─ eval_service.py
│  │  └─ admin_service.py
│  ├─ schemas/              # Pydantic 스키마
│  │  ├─ __init__.py
│  │  ├─ users.py
│  │  ├─ documents.py
│  │  ├─ qna.py
│  │  ├─ eval.py
│  │  └─ prompts.py
│  ├─ templates/            # Jinja 템플릿
│  │  ├─ base.html
│  │  ├─ user/
│  │  │  ├─ dashboard.html
│  │  │  └─ doc_detail.html
│  │  └─ admin/
│  │     ├─ admin_dashboard.html
│  │     ├─ admin_users.html
│  │     ├─ admin_user_detail.html
│  │     ├─ admin_qna_logs.html
│  │     └─ admin_prompts.html
│  ├─ static/               # 정적 파일 (css, js, images)
│  │  ├─ css/
│  │  └─ js/
│  └─ utils/                # 공통 유틸 (로깅 등)
│     ├─ __init__.py
│     └─ logging.py
├─ migrations/              # 스키마 버전 관리(선택)
├─ tests/                   # 테스트 코드
├─ pyproject.toml           # uv/빌드 설정
├─ spec.md                  # (이 문서)
└─ README.md
```

---

## 3. 개발 환경 스펙 (uv 기준)

### 3.1 기본 원칙

- Python 의존성/venv 관리는 **uv**로 통일
- 모든 실행 커맨드는 `uv run ...` 형태로 감싸는 것을 권장

### 3.2 초기 셋업 예시 (컨벤션)

> 실제 버전/패키지 목록은 별도 `pyproject.toml`에서 정의

```bash
# 1) 가상환경 생성
uv venv

# 2) 의존성 설치 (예시)
uv pip install fastapi uvicorn[standard] jinja2 httpx pydantic     sqlalchemy aiosqlite python-multipart

# 3) 개발 서버 실행
uv run uvicorn app.main:app --reload
```

- Tailwind는
  - CDN 방식으로 먼저 시작하거나,
  - 추후 Node 기반 빌드 파이프라인을 별도 디렉터리에서 구성.

---

## 4. FastAPI 레이어 설계

### 4.1 주요 라우터

- `auth.py`
  - 로그인/로그아웃(간단 세션 기반 또는 토큰 기반)
  - 관리자/일반 사용자 권한 구분

- `user_docs.py`
  - `GET /docs` : 내 문서 목록
  - `GET /docs/{doc_id}` : 문서 상세 + QnA/평가 탭 렌더링
  - `POST /docs/upload` : 문서 업로드 처리 (파일 + 메타데이터)
  - `POST /docs/{doc_id}/delete` : 문서 삭제(또는 status 변경)

- `qna.py`
  - `POST /qna/{doc_id}`
    - 요청: 질문 텍스트
    - 처리: File Search + `gemini-2.5-flash` 호출
    - 응답: 답변 텍스트 (AJAX or SSR 리다이렉트)

- `eval.py`
  - `POST /evaluate/{doc_id}`
    - 요청: 평가 템플릿 ID(선택)
    - 처리: File Search + `gemini-2.5-pro` 호출, 결과 DB 저장
  - `GET /evaluate/{doc_id}`
    - 문서별 평가 결과 목록/상세 조회

- `admin.py`
  - `GET /admin` : 대시보드 메인
  - `GET /admin/users` : 사용자 목록
  - `GET /admin/users/{user_id}` : 사용자 상세(문서/평가/QnA)
  - `GET /admin/qna-logs` : QnA 로그 리스트
  - `GET /admin/prompts` : 시스템 프롬프트 목록
  - `POST /admin/prompts` : 새 프롬프트 생성/버전 업

### 4.2 서비스 레이어 역할

- `file_search_service.py`
  - File Search Store 관리
  - 파일 업로드 + 인덱싱
  - `metadataFilter` 조건 문자열 생성
- `qna_service.py`
  - QnA용 시스템 프롬프트 조회
  - File Search + `gemini-2.5-flash` 호출
  - QnA 로그 저장
- `eval_service.py`
  - 평가용 템플릿/프롬프트 조회
  - A/B 문서 컨텍스트 구성
  - `gemini-2.5-pro` 호출 및 결과 파싱
  - `evaluation_runs`, `evaluation_reports` 업데이트
- `admin_service.py`
  - 집계 통계 조회
  - 프롬프트 CRUD
  - QnA 로그/평가 로그 조회

---

## 5. DB 사용 스펙 (SQLite3)

### 5.1 일반 정책

- DB 파일 위치: `./data/app.db` (또는 환경변수로 지정)
- 연결:
  - 개발 단계: 싱글 프로세스/싱글 인스턴스 가정
  - `PRAGMA foreign_keys = ON;` 필수
- 동시성 정책:
  - WAL 모드 사용 권장
  - 평가/QnA 로그는 필수 정보 위주로만 저장 (과도한 쓰기 회피)

### 5.2 주요 엔티티 (요약)

- `users` : 일반 사용자 계정
- `admins` : 관리자 계정
- `file_search_stores` : File Search Store 메타
- `documents` : A/B 문서 메타, `user_id`, `random_key`, `store_id`
- `system_prompts` : QnA/평가용 시스템 프롬프트 버전 관리
- `evaluation_templates` : 평가 템플릿 + B 문서 연결
- `evaluation_runs` : 평가 실행 이력
- `evaluation_reports` : 평가 결과
- `qa_logs` : 문서 기반 QnA 로그

> 상세 컬럼/DDL은 `schema.sql` 또는 `ddl.md`에서 관리.

---

## 6. LLM & File Search 연동 스펙 (상위 개발 기준)

### 6.1 설정/환경변수

- `GOOGLE_API_KEY` : Gemini API 키
- `GEMINI_QNA_MODEL` : 기본값 `gemini-2.5-flash`
- `GEMINI_EVAL_MODEL` : 기본값 `gemini-2.5-pro`
- `FS_MAIN_STORE_NAME` : `fileSearchStores/main-store`
- `FS_RUBRIC_STORE_NAME` : `fileSearchStores/rubric-store`

### 6.2 QnA 호출 플로우 (요약)

1. `qna.py` 라우터에서 `doc_id`, `question` 수신
2. DB에서 `documents` 조회 → `user_id`, `random_key`, `store_id`
3. `qna_service`에서:
   - `system_prompts`에서 type='qna', is_active=1 최신 버전 조회
   - File Search Tool 설정:
     - store: `FS_MAIN_STORE_NAME`
     - metadataFilter: `user_id="<user_id>" AND random_key="<random_key>"`
   - `gemini-2.5-flash`에 generate 요청
4. 응답 텍스트를 `qa_logs`에 저장 후, 사용자에게 반환

### 6.3 평가 호출 플로우 (요약)

1. `eval.py` 라우터에서 `doc_id`, `template_id` 수신
2. DB에서:
   - A 문서 정보(documents)
   - 평가 템플릿(evaluation_templates)
   - B 문서(documents.role='B')
   - 평가용 시스템 프롬프트(system_prompts 또는 템플릿 연결)
3. `evaluation_runs`에 실행 레코드 생성(status='pending')
4. `eval_service`에서:
   - File Search 설정:
     - main-store: A 문서 (user_id + random_key 필터)
     - rubric-store: B 문서(rubric_doc_id 기반)
   - `gemini-2.5-pro` 호출
   - 결과 파싱 → `evaluation_reports` 저장
   - `evaluation_runs.status='success'` 업데이트

---

## 7. 템플릿 & UI 스펙 (개발 기준)

### 7.1 Tailwind 적용

- 초기에는 CDN 사용 (예: `<script src="https://cdn.tailwindcss.com"></script>`)
- 공통 레이아웃: `base.html`에 Tailwind 로딩 + 헤더/푸터 정의
- 페이지별 템플릿은 `base.html`을 `extends`하여 구성

### 7.2 UI 기본 구조

- 사용자 화면:
  - 문서 목록: 테이블 + 업로드 버튼
  - 문서 상세:
    - 문서 메타정보 (제목, 업로드 시간)
    - QnA 영역 (질문 입력 폼 + 답변 영역)
    - 평가 영역 (평가 실행 버튼 + 결과 리스트)
- 관리자 화면:
  - 대시보드: 카드/그래프(간단 텍스트 카드 중심)
  - 사용자 목록/상세
  - QnA 로그 테이블
  - 프롬프트 관리 폼

---

## 8. 로깅/에러 처리 (간단 정책)

- 공통 로깅 유틸(`utils/logging.py`)에서 Python `logging` 설정
- LLM 호출 실패, File Search 에러, DB 예외는
  - 내부 로그에 스택/상세 메시지 기록
  - 사용자에게는 일반화된 오류 메시지 + 재시도 안내 표시
- 중요 이벤트(평가 실행, 프롬프트 변경)는
  - 별도의 audit 로그 또는 관리자 화면에서 식별 가능하게 표현

---

## 9. 향후 확장 고려 메모

- DB를 PostgreSQL로 교체할 수 있도록
  - ORM 사용 또는 Repository 패턴으로 DB 접근 추상화
- LLM/모델 버전을 설정 파일로 관리하여
  - 새 모델로의 전환을 코드 수정 없이 가능하게 할 것
- 평가 작업이 길어질 경우를 대비해
  - 비동기 큐(예: Celery, RQ 등) 도입 여지 열어두기

---

본 spec.md는 **개발자가 실제 코드를 작성할 때 참고하는 상위 스펙** 역할을 하며,  
세부 API 설계, DDL, 화면 설계는 각 전용 문서에서 보완한다.
