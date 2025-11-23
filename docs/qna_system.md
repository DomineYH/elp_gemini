# QnA 챗봇 시스템 상세 분석

> 작성일: 2025-01-23
> 분석 대상: elp_gemini QnA 시스템
> 분석 방법: 코드 리뷰 및 아키텍처 분석

## 📊 1. 전체 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                        사용자 (웹 브라우저)                           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FastAPI 라우터 레이어                            │
│  ┌──────────────────┬──────────────────┬──────────────────────┐    │
│  │ POST /sessions   │ POST /ask        │ GET /history         │    │
│  │ (세션 생성)       │ (질문하기)        │ (히스토리 조회)       │    │
│  └──────────────────┴──────────────────┴──────────────────────┘    │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        QnA Service 레이어                            │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              ask_question() - 핵심 질문 처리 로직              │  │
│  └───────────────────────────────────────────────────────────────┘  │
│              │                                     │                 │
│              ▼                                     ▼                 │
│  ┌─────────────────────┐              ┌─────────────────────────┐  │
│  │  Vector Search      │              │  File Search            │  │
│  │  (평가기준 벡터)     │              │  (문서 검색)             │  │
│  └─────────────────────┘              └─────────────────────────┘  │
└────────────┬─────────────────────────────────────┬──────────────────┘
             │                                     │
             ▼                                     ▼
┌──────────────────────────┐        ┌────────────────────────────────┐
│ CriteriaContextService   │        │   Gemini File Search API       │
│  (평가기준 컨텍스트)      │        │  ┌──────────┬──────────────┐  │
│         │                │        │  │rubricstore│user{id}store │  │
│         ▼                │        │  │(평가기준)  │(사용자 문서)  │  │
│ CriteriaVectorService    │        │  └──────────┴──────────────┘  │
│  (벡터 검색)             │        │                                │
└──────────────────────────┘        └────────────────────────────────┘
             │                                     │
             │                                     │
             └─────────────┬───────────────────────┘
                           ▼
                  ┌─────────────────┐
                  │  최종 답변 생성  │
                  │  (Gemini API)   │
                  └─────────────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │   DB 저장       │
                  │ (ChatMessage)   │
                  └─────────────────┘
```

## 🔄 2. 질문 처리 상세 플로우

```
[사용자 질문]
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 1: 세션 검증                                               │
│  - 세션 존재 확인 (qna_service.py:58-63)                       │
│  - 사용자 권한 확인                                             │
└────────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 2: Vector Search - 평가기준 컨텍스트 검색                  │
│  (qna_service.py:77-109)                                       │
│                                                                 │
│  1. CriteriaContextService.get_context() 호출                  │
│     └─→ CriteriaVectorService.search_criteria()               │
│         └─→ Gemini File Search API (rubricstore 검색)         │
│                                                                 │
│  2. 검색 결과 처리                                              │
│     - response_text: 평가기준 관련 내용                        │
│     - citations: 인용 정보 (title, file_path 등)              │
│     - criteria_ids: 사용된 평가기준 ID 목록                    │
│                                                                 │
│  3. 프롬프트에 "참고 자료" 섹션으로 추가                        │
│     criteria_context = "\n\n### [참고 자료: 관련 평가 기준]"  │
└────────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 3: 대화 히스토리 로드                                      │
│  (qna_service.py:70-75)                                        │
│  - 최근 5개 질문-답변 쌍 가져오기                               │
│  - 컨텍스트 연속성 유지                                         │
└────────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 4: File Search Store ID 결정                              │
│  (qna_service.py:119-182)                                      │
│                                                                 │
│  ┌──────────────────────────────────────────┐                 │
│  │ 4-1. rubricstore (평가기준 스토어) 조회   │                 │
│  │  - "rubricstore" 문자열 포함 스토어 검색  │                 │
│  │  - 없으면 rubric_store_name으로 생성      │                 │
│  └──────────────────────────────────────────┘                 │
│                                                                 │
│  ┌──────────────────────────────────────────┐                 │
│  │ 4-2. user{id}store (사용자 스토어) 조회   │                 │
│  │  - "user{id}store" 패턴 스토어 검색       │                 │
│  │  - 없으면 user-{id}-store 이름으로 생성   │                 │
│  └──────────────────────────────────────────┘                 │
│                                                                 │
│  최종 store_ids = [rubricstore, user{id}store]                │
└────────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 5: Gemini API 호출 (File Search RAG)                      │
│  (qna_service.py:193-206)                                      │
│                                                                 │
│  generate_content(                                             │
│    model = gemini-2.5-flash                                    │
│    contents = full_prompt + question                           │
│    tools = FileSearch(                                         │
│      file_search_store_names = [rubricstore, user{id}store]   │
│    )                                                            │
│  )                                                              │
│                                                                 │
│  ► Gemini가 두 스토어에서 관련 문서 검색 및 답변 생성          │
└────────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 6: Citation 정보 추출 및 확장                              │
│  (qna_service.py:210-240)                                      │
│                                                                 │
│  1. File Search Citations 추출                                 │
│     - grounding_metadata에서 출처 정보 추출                    │
│     - 문서 제목, URI 등                                        │
│                                                                 │
│  2. Vector Search 평가기준 Citations 추가                      │
│     - criteria_metadata를 citations에 병합                     │
│     - 확장된 Citations 생성                                     │
│       {                                                         │
│         "documents": { File Search 출처 },                     │
│         "criteria": [ Vector Search 평가기준 출처 ]            │
│       }                                                         │
└────────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 7: DB 저장 (ChatMessage)                                  │
│  (qna_service.py:244-252)                                      │
│                                                                 │
│  1. 사용자 질문 저장 (role=USER)                               │
│  2. 어시스턴트 답변 저장 (role=ASSISTANT)                       │
│     - citations: 확장된 출처 정보                              │
│     - used_criteria_ids: 사용된 평가기준 ID 목록               │
└────────────────────────────────────────────────────────────────┘
     │
     ▼
[답변 반환]
```

## 🏗️ 3. 핵심 컴포넌트 상세 설명

### 3.1 QnAService (app/services/qna_service.py)

**역할**: QnA 시스템의 핵심 오케스트레이터

**주요 메서드**:
- `ask_question()` (36-272줄): 질문 처리 메인 로직
- `_build_context()` (274-291줄): 대화 컨텍스트 구성
- `_extract_citations()` (293-334줄): Citation 정보 추출
- `_extend_citations()` (336-369줄): Vector Search 출처 추가
- `_save_messages()` (392-433줄): DB 저장

**핵심 로직 (ask_question)**:
```python
# 1. 세션 검증
session = await self._get_session(session_id, user_id)

# 2. Vector Search (평가기준 컨텍스트)
criteria_service = CriteriaContextService(db=self.db)
criteria_result = await criteria_service.get_context(question)
criteria_context = "### [참고 자료]" + context_text

# 3. 대화 히스토리
conversation_history = await self.get_conversation_history(session_id, limit=5)

# 4. Store IDs 결정
store_ids = [rubricstore, user{id}store]

# 5. Gemini API 호출 (File Search)
response = self.client.models.generate_content(
    model=gemini-2.5-flash,
    contents=full_prompt + question,
    tools=[FileSearch(file_search_store_names=store_ids)]
)

# 6. Citations 확장
extended_citations = self._extend_citations(citations, criteria_metadata)

# 7. DB 저장
await self._save_messages(...)
```

### 3.2 CriteriaContextService (app/services/criteria_context_service.py)

**역할**: Vector Search를 통한 평가기준 컨텍스트 제공

**주요 메서드**:
- `get_context()` (22-99줄): 평가기준 검색 및 메타데이터 추출

**동작 방식**:
```python
async def get_context(self, question: str) -> Dict[str, Any]:
    # 1. Vector Search로 평가기준 검색
    result = await self.vector_service.search_criteria(
        query=question,
        temperature=0.3  # 정확도 중시
    )

    # 2. Citations에서 평가기준 정보 추출
    for citation in citations:
        title = citation.get("title")
        # DB에서 title로 Criteria 찾기
        criteria = await self.db.execute(
            select(Criteria).where(
                Criteria.title.like(f"%{title}%"),
                Criteria.status == "active"
            )
        )

        # 3. 평가기준 메타데이터 수집
        criteria_metadata.append({
            "id": criteria.id,
            "title": criteria.title,
            "file_path": criteria.file_path
        })

    return {
        "context_text": response_text,  # 프롬프트에 추가될 텍스트
        "criteria_ids": [...],          # 사용된 평가기준 ID
        "criteria_metadata": [...],     # 평가기준 메타데이터
        "citations": [...]              # 원본 citations
    }
```

### 3.3 CriteriaVectorService (app/services/criteria_vector_service.py)

**역할**: 평가기준 Vector DB 관리 및 검색

**주요 메서드**:
- `upload_criteria()` (25-93줄): 평가기준 업로드 (Store 재생성 옵션)
- `search_criteria()` (189-245줄): 평가기준 검색
- `_recreate_criteria_store()` (137-187줄): Store 재생성 (기존 삭제 후 생성)

**검색 로직**:
```python
async def search_criteria(
    self,
    query: str,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7
) -> Dict[str, Any]:
    # 1. rubricstore 찾기
    for s in client.file_search_stores.list():
        if s.display_name == self.store_name:
            store = s
            break

    # 2. metadata_filter 설정
    metadata_filter = 'type="criteria"'

    # 3. File Search로 검색
    result = await self.file_search_service.search_in_store(
        query=query,
        store_name=store.name,
        metadata_filter=metadata_filter,
        temperature=temperature
    )

    return {
        "response_text": ...,
        "citations": ...,
        "sources_count": ...
    }
```

### 3.4 FileSearchService (app/services/file_search_service.py)

**역할**: Gemini File Search API 관리

**주요 메서드**:
- `upload_document()` (94-196줄): 문서 업로드 및 인덱싱
- `search_in_store()` (258-323줄): Store에서 문서 검색
- `delete_store_by_display_name()` (213-256줄): Store 삭제
- `_get_or_create_store()` (75-92줄): Store 조회 또는 생성

**업로드 프로세스**:
```python
async def upload_document(
    self,
    file_path: str,
    display_name: str,
    metadata: Dict[str, Any],
    store_type: str = "main"
) -> Dict[str, str]:
    # 1. Store 선택 (rubric / user-{id}-store)
    if store_type == "rubric":
        store_name = self.rubric_store_name
    else:
        user_id = metadata.get("user_id")
        store_name = f"user-{user_id}-store"

    # 2. Store 조회/생성
    store = self._get_or_create_store(store_name)

    # 3. 파일 업로드 및 인덱싱
    operation = self.client.file_search_stores.upload_to_file_search_store(
        file_search_store_name=store.name,
        file=file_path,
        config={
            'chunking_config': {
                'white_space_config': {
                    'max_tokens_per_chunk': 500,
                    'max_overlap_tokens': 100
                }
            },
            'custom_metadata': custom_metadata
        }
    )

    # 4. Polling (인덱싱 완료 대기)
    while not operation.done:
        await asyncio.sleep(poll_interval)
        operation = self.client.operations.get(operation)

    return {
        "document_id": operation.response.document_name,
        "store_id": operation.response.parent
    }
```

## 🗃️ 4. 데이터베이스 스키마

### ChatSession
```python
- id: int (PK)
- user_id: int (FK → users)
- title: str (세션 제목 / 문서 ID)
- created_at: datetime
- updated_at: datetime
```

### ChatMessage
```python
- id: int (PK)
- session_id: int (FK → chat_sessions)
- role: MessageRole (USER / ASSISTANT)
- content: str (질문 / 답변 내용)
- model_name: str (사용된 모델)
- citations: JSON (출처 정보)
- used_criteria_ids: JSON (사용된 평가기준 ID 목록)
- created_at: datetime
```

## 🔑 5. 핵심 특징 및 설계 의도

### 5.1 이중 검색 시스템 (Dual Search)

**Why?** 평가기준을 두 가지 방식으로 활용하여 답변 품질 향상

1. **Vector Search (참고 자료)**
   - 목적: 평가기준을 프롬프트의 "참고 자료"로 제공
   - 장점: AI가 평가기준의 맥락을 이해하고 답변에 반영
   - 구현: CriteriaVectorService → rubricstore 검색

2. **File Search (주요 검색)**
   - 목적: 평가기준 + 사용자 문서를 직접 검색
   - 장점: 원본 문서 기반 정확한 답변
   - 구현: Gemini File Search API → rubricstore + user{id}store

**결과**: Vector Search의 컨텍스트 + File Search의 정확도 = 고품질 답변

### 5.2 Store 격리 전략

**rubricstore** (공유)
- 모든 사용자가 공통으로 사용하는 평가기준
- 시스템 관리자가 관리
- Vector Search와 File Search 모두 참조

**user{id}store** (격리)
- 사용자별 독립적인 문서 저장소
- 개인 문서 보안 및 격리
- File Search만 참조

### 5.3 Citations 확장

**구조**:
```json
{
  "documents": {
    // File Search에서 검색한 문서 출처
    "grounding_chunks": [...]
  },
  "criteria": [
    // Vector Search에서 검색한 평가기준 출처
    {
      "id": 1,
      "title": "평가기준 제목",
      "file_path": "criteria/rubric1.pdf",
      "type": "criteria"
    }
  ]
}
```

**장점**:
- 사용자가 답변의 근거를 명확히 확인 가능
- 평가기준과 문서 출처를 구분하여 제공
- 투명성 및 신뢰도 향상

### 5.4 세션 기반 대화 관리

- 세션당 최근 5개 질문-답변 쌍 유지
- 컨텍스트 연속성 보장
- 대화 히스토리를 통한 맥락 이해

## 📝 6. API 엔드포인트

### 6.1 POST /api/qna/sessions
**기능**: QnA 세션 생성

**요청**:
```json
{
  "lessonplan_filename": "lesson1.pdf"
}
```

**응답**:
```json
{
  "session_id": 1,
  "user_id": 123,
  "lessonplan_filename": "lesson1.pdf",
  "created_at": "2025-01-01T00:00:00Z"
}
```

### 6.2 POST /api/qna/sessions/{session_id}/ask
**기능**: 세션에서 질문하기

**요청**:
```json
{
  "question": "이 평가기준의 핵심은 무엇인가요?"
}
```

**응답**:
```json
{
  "session_id": 1,
  "question": "이 평가기준의 핵심은 무엇인가요?",
  "answer": "이 평가기준의 핵심은...",
  "latency_ms": 1234,
  "citations": {
    "documents": {...},
    "criteria": [...]
  }
}
```

### 6.3 GET /api/qna/sessions/{session_id}/history
**기능**: 대화 히스토리 조회

**응답**:
```json
{
  "session_id": 1,
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "질문 1",
      "created_at": "..."
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "답변 1",
      "created_at": "..."
    }
  ],
  "total_count": 10
}
```

### 6.4 POST /api/qna/{document_id:path}
**기능**: 문서와 대화하기 (자동 세션 관리)

**특징**:
- 문서 ID 기반 세션 자동 생성/조회
- 세션이 없으면 자동 생성
- document_id에서 store_id 추출하여 검색 범위 지정

## 🔄 7. 시퀀스 다이어그램

### 7.1 질문 처리 전체 시퀀스

```
사용자      FastAPI      QnAService    CriteriaContext    Gemini API         DB
  │           │              │                │               │              │
  │──질문───→│              │                │               │              │
  │           │──ask()─────→│                │               │              │
  │           │              │                │               │              │
  │           │              │──세션 검증────┼───────────────┼─────────────→│
  │           │              │←─────────────────────────────────────────────│
  │           │              │                │               │              │
  │           │              │─get_context()→│               │              │
  │           │              │                │─search────────→│              │
  │           │              │                │  (rubricstore) │              │
  │           │              │                │←──결과─────────│              │
  │           │              │←평가기준 컨텍스트─│               │              │
  │           │              │                │               │              │
  │           │              │─get_history()─┼───────────────┼─────────────→│
  │           │              │←─────────────────────────────────────────────│
  │           │              │                │               │              │
  │           │              │─Store IDs 결정─│               │              │
  │           │              │ (rubricstore,  │               │              │
  │           │              │  user{id}store)│               │              │
  │           │              │                │               │              │
  │           │              │─generate_content()────────────→│              │
  │           │              │  (FileSearch w/ 2 stores)      │              │
  │           │              │←──답변 + citations─────────────│              │
  │           │              │                │               │              │
  │           │              │─extend_citations()─│               │              │
  │           │              │←──확장된 citations─│               │              │
  │           │              │                │               │              │
  │           │              │─save_messages()┼───────────────┼─────────────→│
  │           │              │←─────────────────────────────────────────────│
  │           │←─답변 반환───│                │               │              │
  │←─────────│              │                │               │              │
```

### 7.2 평가기준 업로드 시퀀스

```
관리자    CriteriaVectorService    FileSearchService    Gemini API
  │              │                        │                 │
  │─업로드 요청→│                        │                 │
  │              │                        │                 │
  │              │─recreate_store()──────→│                 │
  │              │                        │─list()─────────→│
  │              │                        │←──store 목록────│
  │              │                        │                 │
  │              │                        │─delete(force)──→│
  │              │                        │←──OK───────────│
  │              │                        │                 │
  │              │                        │─create()───────→│
  │              │                        │←──new store────│
  │              │←───────────────────────│                 │
  │              │                        │                 │
  │              │─upload_document()─────→│                 │
  │              │                        │─upload()───────→│
  │              │                        │←──operation────│
  │              │                        │                 │
  │              │                        │─polling────────→│
  │              │                        │←──done─────────│
  │              │←─document_id, store_id─│                 │
  │←─성공 응답───│                        │                 │
```

## 🛠️ 8. 기술 스택 및 의존성

### 8.1 핵심 기술
- **Framework**: FastAPI (비동기 웹 프레임워크)
- **AI**: Google Gemini API (gemini-2.5-flash)
- **Database**: SQLite3 (AsyncSession)
- **ORM**: SQLAlchemy (비동기)

### 8.2 주요 라이브러리
```python
from google import genai                        # Gemini SDK
from google.genai import types                  # Gemini 타입
from sqlalchemy.ext.asyncio import AsyncSession # 비동기 DB
import asyncio                                  # 비동기 처리
```

### 8.3 환경 변수 (app/config.py)
```python
GOOGLE_API_KEY: str                    # Gemini API 키
GEMINI_QNA_MODEL: str                  # QnA 모델 (gemini-2.5-flash)
QNA_TEMPERATURE: float                 # 생성 온도 (기본: 0.7)

FS_MAIN_STORE_NAME: str                # 메인 스토어 이름
FS_RUBRIC_STORE_NAME: str              # 평가기준 스토어 이름

FS_CHUNKING_MAX_TOKENS: int            # 청크 최대 토큰 (기본: 500)
FS_CHUNKING_OVERLAP_TOKENS: int        # 청크 오버랩 토큰 (기본: 100)

FS_UPLOAD_TIMEOUT: int                 # 업로드 타임아웃 (초)
FS_POLL_INTERVAL: int                  # Polling 간격 (초)
```

## 🔍 9. 디버깅 및 모니터링

### 9.1 로깅 전략
```python
# qna_service.py
logger.info(f"QnA FileSearch 호출\n"
            f"  - session_id: {session_id}\n"
            f"  - user_id: {user_id}\n"
            f"  - 평가기준 스토어: {rubric_store_id}\n"
            f"  - 사용자 스토어: {user_store_id}\n"
            f"  - 총 스토어 개수: {len(store_ids)}")

logger.info(f"검색된 Citations: {sources_count}개")

logger.info(f"QnA 완료: session={session_id}, "
            f"latency={latency_ms}ms, sources={sources_count}")
```

### 9.2 주요 로그 포인트
- **세션 생성**: qna.py:69-74
- **질문 처리 시작**: qna_service.py:184-191
- **평가기준 검색**: criteria_context_service.py:102-105
- **Citations 추출**: qna_service.py:235
- **QnA 완료**: qna_service.py:254-257

### 9.3 에러 핸들링
```python
# 각 레이어별 에러 처리
try:
    # 서비스 로직
except ValueError as e:
    # 사용자 입력 오류
    raise HTTPException(status_code=404, detail=str(e))
except Exception as e:
    # 서버 오류
    logger.error(f"처리 실패: {str(e)}", exc_info=True)
    raise HTTPException(status_code=500, detail="...")
```

## 📈 10. 향후 개선 방향

### 10.1 성능 개선
1. **병렬 처리**
   ```python
   # Vector Search와 File Search를 병렬로 실행
   criteria_task = asyncio.create_task(criteria_service.get_context(question))
   history_task = asyncio.create_task(self.get_conversation_history(session_id))

   criteria_result, history = await asyncio.gather(criteria_task, history_task)
   ```

2. **캐싱 레이어**
   ```python
   # Redis 캐싱 추가
   cache_key = f"vector_search:{hash(question)}"
   cached_result = await redis.get(cache_key)
   if cached_result:
       return cached_result
   ```

3. **Store 풀링**
   ```python
   # 자주 사용하는 Store를 메모리에 캐싱
   class StorePool:
       _pool = {}

       @classmethod
       async def get_store(cls, store_name):
           if store_name not in cls._pool:
               cls._pool[store_name] = await fetch_store(store_name)
           return cls._pool[store_name]
   ```

### 10.2 기능 확장
1. **스트리밍 응답**: Gemini API의 스트리밍 기능 활용
2. **멀티모달**: 이미지 첨부 질문 지원
3. **컨텍스트 윈도우 확장**: 5개 → 10개 대화 쌍
4. **평가기준 가중치**: 중요도에 따른 평가기준 우선순위

### 10.3 모니터링 강화
1. **성능 메트릭**: 응답 시간, Citations 개수 추적
2. **사용량 통계**: 사용자별/세션별 질문 수 집계
3. **품질 측정**: 사용자 피드백 기반 답변 품질 평가

## 📚 11. 참고 자료

### 11.1 관련 파일 위치
```
app/
├── routers/
│   └── qna.py                           # API 엔드포인트
├── services/
│   ├── qna_service.py                   # QnA 메인 서비스
│   ├── criteria_context_service.py      # Vector Search 컨텍스트
│   ├── criteria_vector_service.py       # 평가기준 벡터 관리
│   ├── file_search_service.py           # File Search API 관리
│   └── prompt_loader_service.py         # 프롬프트 로드
├── models/
│   ├── chat_sessions.py                 # 세션 모델
│   ├── chat_messages.py                 # 메시지 모델
│   └── criteria.py                      # 평가기준 모델
└── schemas/
    └── sessions.py                       # API 스키마
```

### 11.2 핵심 코드 라인 참조
- **QnA 메인 로직**: app/services/qna_service.py:36-272
- **Vector Search**: app/services/criteria_context_service.py:22-99
- **File Search**: app/services/file_search_service.py:258-323
- **Store 관리**: app/services/file_search_service.py:75-92
- **API 엔드포인트**: app/routers/qna.py:95-163

---

## ✅ 요약

QnA 챗봇 시스템은 **이중 검색 시스템**을 통해 고품질 답변을 제공합니다:

1. **Vector Search**: 평가기준을 프롬프트의 "참고 자료"로 제공
2. **File Search**: 평가기준 + 사용자 문서를 직접 검색

**핵심 특징**:
- ✅ Store 격리: rubricstore (공유) + user{id}store (격리)
- ✅ Citations 확장: 문서 + 평가기준 출처 통합
- ✅ 세션 기반: 대화 컨텍스트 유지 (최근 5개 쌍)
- ✅ 비동기 처리: FastAPI + AsyncSession

이 문서는 시스템의 동작 원리를 완전히 이해하고, 향후 개선 및 확장에 활용할 수 있도록 작성되었습니다.
