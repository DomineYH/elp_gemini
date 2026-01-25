# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI RAG Document Evaluation & QnA Platform - 교육용 문서 평가 및 질의응답 시스템

**Tech Stack**: Python 3.10+, FastAPI (async), SQLAlchemy (async), SQLite (WAL mode), Google Gemini API, Jinja2, Tailwind CSS

## Commands

```bash
# 실행
python -m app.main
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 테스트
pytest                           # 전체 테스트
pytest tests/test_foo.py         # 단일 파일
pytest tests/test_foo.py::test_bar  # 단일 테스트
pytest --cov=app tests/          # 커버리지 포함

# 린트/포맷
black --line-length 80 app/
ruff check app/

# 설치
pip install -e .          # 기본 설치
pip install -e ".[dev]"   # 개발 의존성 포함
```

## Architecture

### 이중 검색 시스템 (Dual Search System)

QnA 서비스는 Vector Search와 File Search를 결합합니다:

```
사용자 질문
    │
    ├─→ Vector Search (평가기준 벡터 DB)
    │   └─→ CriteriaContextService → 프롬프트 "참고 자료"
    │
    └─→ File Search (Gemini API)
        ├─→ rubricstore (평가기준 문서, 모든 사용자 공유)
        └─→ user{id}store (사용자별 업로드 문서)
```

### 핵심 서비스 계층

| 서비스 | 위치 | 역할 |
|--------|------|------|
| QnAService | `app/services/qna_service.py` | 세션 기반 QnA 처리, 이중 검색 통합 |
| FileSearchService | `app/services/file_search_service.py` | Google File Search API 래퍼 |
| CriteriaVectorService | `app/services/criteria_vector_service.py` | 평가기준 벡터 DB 관리 |
| CriteriaContextService | `app/services/criteria_context_service.py` | Vector Search 컨텍스트 생성 |
| EvaluationService | `app/services/eval_service.py` | 문서 평가 실행 |
| AuthService | `app/services/auth_service.py` | 세션 기반 인증 (bcrypt) |

### 데이터 흐름

**QnA 흐름** (`app/services/qna_service.py:36-180`):
1. ChatSession 검증
2. Vector Search로 평가기준 컨텍스트 검색
3. File Search로 user{id}store + rubricstore 검색
4. Gemini API 호출 (gemini-2.5-flash)
5. 답변 + Citations 저장

**평가 흐름** (`app/services/eval_service.py:42-80`):
1. 평가 기준 벡터 검색
2. 평가 프롬프트 생성 (eval_prompt_builder.py)
3. Gemini API 호출 (gemini-2.0-flash-thinking-exp)
4. 분석 결과 마크다운 저장 (`data/analys/`)

### 인증 미들웨어 스택

```
요청 → CORS → AuthMiddleware (HTML 세션 검증) → SessionMiddleware → 라우터
```

- HTML 요청: 세션 검증 → 미인증 시 /login 리다이렉트
- API 요청: 엔드포인트에서 `get_current_user` 의존성 사용

## Key Environment Variables

```bash
GOOGLE_API_KEY=              # Google AI Studio API 키 (필수)
SECRET_KEY=                  # 세션 암호화 키 32자 이상 (필수)
GEMINI_QNA_MODEL=gemini-2.5-flash
GEMINI_EVAL_MODEL=gemini-2.0-flash-thinking-exp
FS_RUBRIC_STORE_NAME=rubric-store
MAX_UPLOAD_SIZE=52428800     # 50MB
```

## 코드 작성 규칙 (doc/rules.md)

- **파일 길이**: 300 라인 이하
- **라인 길이**: 80자 이하
- **TDD**: 구현 전 실패하는 테스트 먼저 작성
- **출력 언어**: 항상 한글로 출력

## 기본 관리자 계정

- Email: admin@example.com
- Password: admin_password
