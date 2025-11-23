# elp_gemini Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-11-13

## Active Technologies

- Python 3.10+ + FastAPI, Jinja2, SQLite3, Google Gemini API SDK, httpx, pydantic, python-multipart, aiosqlite (001-ai-rag-eval-platform)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.10+: Follow standard conventions

## Recent Changes

- 001-ai-rag-eval-platform: Added Python 3.10+ + FastAPI, Jinja2, SQLite3, Google Gemini API SDK, httpx, pydantic, python-multipart, aiosqlite

<!-- MANUAL ADDITIONS START -->

## QnA 시스템 아키텍처

### 이중 검색 시스템 (Dual Search System)

QnA 서비스는 Vector Search와 File Search를 결합한 이중 검색 시스템을 사용합니다.

#### 1. Vector Search (평가기준 벡터 검색)
- **역할**: 평가기준 관련 컨텍스트를 참고 자료로 제공
- **구현**: CriteriaVectorService를 통한 벡터 DB 검색
- **위치**: app/services/qna_service.py:77-109
- **출력**: 프롬프트의 "참고 자료" 섹션으로 추가

#### 2. File Search (문서 검색)
- **역할**: 평가기준 문서 + 사용자 업로드 문서 검색
- **구현**: Gemini File Search API 사용
- **위치**: app/services/qna_service.py:119-180
- **검색 대상**:
  - rubricstore: 평가기준 문서 (Vector Search의 원본 데이터)
  - user{id}store: 사용자별 업로드 문서

#### 검색 흐름

```
사용자 질문
    │
    ├─→ Vector Search (평가기준 벡터 DB)
    │   └─→ 평가기준 컨텍스트 추출 → 프롬프트 "참고 자료"
    │
    └─→ File Search (Gemini API)
        ├─→ rubricstore (평가기준 문서)
        └─→ user{id}store (사용자 문서)
            └─→ 문서 기반 답변 생성

최종 답변 = Vector Search 컨텍스트 + File Search 결과
```

#### 주요 특징

1. **Vector Search와 rubricstore의 관계**
   - Vector Search는 rubricstore의 평가기준 데이터를 벡터화하여 검색
   - File Search는 rubricstore의 원본 문서를 직접 참조
   - 두 방식 모두 동일한 평가기준 데이터를 활용하여 답변 품질 향상

2. **사용자별 문서 격리**
   - 각 사용자는 독립적인 File Search Store 보유 (user{id}store)
   - 평가기준은 모든 사용자가 공유 (rubricstore)

3. **답변 생성 과정**
   - Step 1: Vector Search로 관련 평가기준 검색
   - Step 2: File Search로 평가기준 문서 + 사용자 문서 검색
   - Step 3: 두 결과를 결합하여 최종 답변 생성

#### 관련 파일
- `app/services/qna_service.py`: QnA 서비스 메인 로직
- `app/services/criteria_context_service.py`: Vector Search 구현
- `app/services/criteria_vector_service.py`: 평가기준 벡터 검색
- `app/services/file_search_service.py`: File Search Store 관리

<!-- MANUAL ADDITIONS END -->

## rules
 - doc/rules.md 를 준수할 것. 
 - 항상 한글로 출력을 할 것. 
