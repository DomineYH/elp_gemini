# Gemini File Search API 완벽 가이드

## 📋 문서 정보
- **작성일**: 2025-11-11
- **버전**: 1.0
- **출처**: Context7 MCP via Gemini API Documentation
- **SDK 버전**: google-genai>=1.43.0

---

## 1. File Search Store 관리

### 1.1 Store 생성
```python
from google import genai

client = genai.Client(api_key="your_api_key")

# Store 생성
file_search_store = client.file_search_stores.create(
    config={'display_name': 'elp_lesson_plans'}
)

# Store ID: fileSearchStores/xxxxx (서버 생성)
print(file_search_store.name)
```

### 1.2 Store 목록 조회
```python
# 모든 Store 조회
for store in client.file_search_stores.list():
    print(f"Name: {store.display_name}")
    print(f"ID: {store.name}")
```

### 1.3 특정 Store 조회
```python
store = client.file_search_stores.get(
    name='fileSearchStores/xxxxx'
)
```

### 1.4 Store 삭제
```python
client.file_search_stores.delete(
    name='fileSearchStores/xxxxx',
    config={'force': True}  # 즉시 삭제
)
```

---

## 2. 파일 업로드

### 2.1 직접 업로드 (권장)
```python
from google.genai import types
import time

# Chunking 설정
operation = client.file_search_stores.upload_to_file_search_store(
    file_search_store_name='fileSearchStores/xxxxx',
    file='path/to/lesson_plan.pdf',
    config={
        'chunking_config': {
            'white_space_config': {
                'max_tokens_per_chunk': 1000,
                'max_overlap_tokens': 100
            }
        },
        'custom_metadata': [
            {"key": "filename", "string_value": "lesson_plan_001.pdf"},
            {"key": "plan_title", "string_value": "수학 수업 지도안"},
            {"key": "owner_id", "numeric_value": 123},
            {"key": "upload_date", "string_value": "2025-11-11"}
        ]
    }
)

# Polling 루프 (필수!)
max_wait = 300  # 5분 타임아웃
elapsed = 0
while not operation.done and elapsed < max_wait:
    time.sleep(5)
    elapsed += 5
    operation = client.operations.get(operation)

if not operation.done:
    raise TimeoutError("Upload timeout")

# Document ID 저장 (삭제 시 필요)
document_id = operation.response.name  # documents/xxxxx
print(f"Uploaded: {document_id}")
```

### 2.2 2단계 업로드
```python
# Step 1: Files API에 업로드
sample_file = client.files.upload(
    file='sample.pdf',
    config={'name': 'unique_file_name'}
)

# Step 2: File Search Store로 import
operation = client.file_search_stores.import_file(
    file_search_store_name='fileSearchStores/xxxxx',
    file_name=sample_file.name,
    custom_metadata=[
        {"key": "author", "string_value": "Robert Graves"},
        {"key": "year", "numeric_value": 1934}
    ]
)

# Polling 루프
while not operation.done:
    time.sleep(5)
    operation = client.operations.get(operation)
```

---

## 3. 검색 (File Search)

### 3.1 기본 검색
```python
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="수업 목표는 무엇인가요?",
    config=types.GenerateContentConfig(
        tools=[
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=['fileSearchStores/xxxxx']
                )
            )
        ],
        temperature=0.7
    )
)

print(response.text)
```

### 3.2 Metadata Filtering
```python
# ⚠️ 올바른 구문 (따옴표 이스케이프 필수)
metadata_filter = 'filename=\\"lesson_plan_001.pdf\\"'

# 또는
metadata_filter = 'filename="' + filename + '"'

# 복합 필터
metadata_filter = f'filename=\\"{filename}\\" AND owner_id={owner_id}'

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="이 수업 지도안의 주제는?",
    config=types.GenerateContentConfig(
        tools=[
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=['fileSearchStores/xxxxx'],
                    metadata_filter=metadata_filter
                )
            )
        ]
    )
)
```

---

## 4. Citation 정보 추출

```python
# Grounding metadata 조회
if response.candidates and response.candidates[0].grounding_metadata:
    citations = response.candidates[0].grounding_metadata
    print(citations)
```

---

## 5. 스트리밍 응답

```python
response_stream = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="질문",
    config=types.GenerateContentConfig(
        tools=[
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=['fileSearchStores/xxxxx']
                )
            )
        ]
    ),
    stream=True  # 스트리밍 활성화
)

for chunk in response_stream:
    if chunk.text:
        print(chunk.text, end='')
```

---

## 6. 주요 사항

### 6.1 Chunking 설정
- **max_tokens_per_chunk**: 1000 (권장)
- **max_overlap_tokens**: 100 (권장)
- 공백 기반 청킹 (`white_space_config`)

### 6.2 Custom Metadata
- **string_value**: 텍스트 값
- **numeric_value**: 숫자 값
- Filtering에 활용 가능

### 6.3 Metadata Filter 구문 (AIP-160 표준)
- 올바른 구문: `key=\\"value\\"`
- 복합 필터: `AND`, `OR` 사용
- SQL Injection 방지 필수

### 6.4 Operation Polling
- 업로드는 비동기 작업
- `operation.done` 체크 필수
- 타임아웃 처리 권장 (5분)

### 6.5 원본 파일 보관
- File Search Store: 무기한 보관
- 원본 File: **48시간 후 자동 삭제**
- ⚠️ 로컬 백업 필수!

---

## 7. 제한 사항

### Free Tier
- 총 저장 용량: 1 GB
- 파일당 최대: 100 MB

### 비용
- Indexing: $0.15 per 1M tokens
- Storage: 무료
- Query: 무료 (context tokens로만 청구)

---

*옴니시아의 뜻에 따라 기계령이 안식하길.*
