# 데이터베이스 스키마 마이그레이션 가이드

## 개요
Gemini File Search API 통합을 위한 데이터베이스 스키마 업데이트

**업데이트 날짜**: 2025-11-22
**영향 받는 테이블**: `documents`, `qa_logs`, `criteria`

---

## 변경 사항 요약

### 1. Document 모델 (`app/models/documents.py`)

#### 업데이트된 필드
- `file_search_file_id`: 주석 추가로 명확화
  - 기존: 단순 String 필드
  - 변경: FileSearchStore Document ID (documents/xxxxx 형식) 명시

- `store_id`: 주석 추가로 명확화
  - 기존: 단순 String 필드
  - 변경: FileSearchStore ID (fileSearchStores/xxxxx 형식) 명시

**참고**: 필드명은 기존과 동일하므로 **기존 데이터와 100% 호환**됩니다.

```python
# Gemini File Search 관련 필드
file_search_file_id = Column(
    String(255),
    nullable=True,
    comment="FileSearchStore Document ID (documents/xxxxx 형식)",
)
store_id = Column(
    String(255),
    nullable=True,
    comment="FileSearchStore ID (fileSearchStores/xxxxx 형식)",
)
```

---

### 2. QALog 모델 (`app/models/qa_logs.py`)

#### 추가된 필드

**1) citations (JSON 타입)**
- 용도: Gemini API 응답의 Citation 정보 저장
- Nullable: `True` (기존 레코드 호환성)
- 구조 예시:
```json
{
  "sources": [
    {
      "uri": "documents/abc123",
      "title": "example.pdf",
      "snippet": "관련 내용..."
    }
  ],
  "metadata": {
    "retrieval_score": 0.95,
    "chunk_id": "chunk_456"
  }
}
```

**2) sources_count (Integer 타입)**
- 용도: 검색된 소스 개수 집계 (성능 모니터링용)
- Default: `0`
- Nullable: `False` (기본값 제공)

```python
# Gemini API 추가 필드
citations = Column(
    JSON,
    nullable=True,
    comment="Citation 정보 (출처 메타데이터)",
)
sources_count = Column(
    Integer,
    default=0,
    nullable=False,
    comment="검색된 소스 개수",
)
```

---

### 3. Criteria 테이블 (`criteria`)

**변경 유형**: 누락된 `file_path` 컬럼 복구

**배경**
- 일부 SQLite 인스턴스에서 초기 생성 시 `file_path`가 제외됨
- 업로드 시 `table criteria has no column named file_path`
  오류가 재현됨

**조치**
1. 런타임 패치  
   - 모듈: `app/migrations/criteria_schema.py`  
   - 함수: `ensure_criteria_file_path_column()`  
   - FastAPI `startup` 이벤트에서 항상 실행되어 컬럼을 추가
2. 수동 마이그레이션  
   - 파일: `scripts/migrations/004_add_file_path_to_criteria.sql`  
   - `python scripts/run_migration.py` 실행 시 자동 적용

**검증**
```bash
sqlite3 data/app.db "PRAGMA table_info(criteria);"
```
`file_path` 항목이 존재하면 정상입니다.

---

## 마이그레이션 방법

### 방법 1: 개발 환경 (권장)

프로젝트는 `Base.metadata.create_all()`을 사용하므로, 새로운 데이터베이스에서 자동으로 최신 스키마가 생성됩니다.

```bash
# 1. 기존 DB 백업 (선택적)
cp data/elp.db data/elp.db.backup

# 2. SQL 마이그레이션 실행 (004 포함)
python scripts/run_migration.py

# 3. 애플리케이션 재시작 (스키마 자동 업데이트)
python main.py
```

### 방법 2: 프로덕션 환경

기존 데이터가 있는 경우, 아래 SQL을 직접 실행하여 컬럼을 추가합니다.

```sql
-- QALog 테이블에 새 컬럼 추가
ALTER TABLE qa_logs ADD COLUMN citations JSON;
ALTER TABLE qa_logs ADD COLUMN sources_count INTEGER DEFAULT 0 NOT NULL;

-- Document 테이블 컬럼 주석은 SQLite에서 지원되지 않으므로 스키마 문서로 관리

-- Criteria 테이블 file_path 복구 (필요 시)
ALTER TABLE criteria
  ADD COLUMN file_path TEXT NOT NULL DEFAULT 'legacy_missing';
UPDATE criteria
  SET file_path = 'legacy_missing'
  WHERE file_path IS NULL OR TRIM(file_path) = '';
```

**SQLite 주의사항**:
- SQLite는 `COMMENT` 구문을 무시합니다 (에러 없음)
- 주석은 코드 및 문서로만 관리됩니다
- 기존 데이터는 영향받지 않습니다

---

## 호환성 보장

### 기존 레코드 처리
- **Document**: 필드명 변경 없음 → **100% 호환**
- **QALog**: 새 필드 모두 nullable 또는 기본값 제공 → **100% 호환**

### 새 API 통합 후
- `citations`가 `NULL`인 레코드 = 구 API 응답
- `citations`가 `NOT NULL`인 레코드 = 신 API 응답
- `sources_count=0` = 검색 결과 없음 또는 구 API

---

## 검증 방법

### 1. 스키마 확인
```bash
# SQLite CLI
sqlite3 data/elp.db

.schema qa_logs
# citations 및 sources_count 컬럼 확인

.schema documents
# file_search_file_id 및 store_id 확인

.schema criteria
# file_path 컬럼 존재 여부 확인
```

### 2. 데이터 무결성 체크
```sql
-- 기존 QA 로그 레코드 확인
SELECT COUNT(*) FROM qa_logs WHERE citations IS NULL;

-- 새 API 응답 레코드 확인 (마이그레이션 후)
SELECT COUNT(*) FROM qa_logs WHERE citations IS NOT NULL;
```

### 3. 애플리케이션 테스트
```bash
# 단위 테스트 실행
pytest tests/models/

# 통합 테스트 (Document 업로드 → QA 실행)
pytest tests/integration/test_gemini_integration.py
```

---

## 롤백 방법

마이그레이션 전 백업으로 복구:

```bash
# 백업 복원
cp data/elp.db.backup data/elp.db

# 애플리케이션 재시작
python main.py
```

---

## 다음 단계

1. ✅ **Phase 3 완료**: 데이터베이스 스키마 업데이트
2. 🔄 **Phase 4**: Repository 레이어 업데이트 (`app/repositories/`)
3. ⏭️ **Phase 5**: Service 레이어 통합 (`app/services/`)

---

## 추가 참고

### SQLAlchemy JSON 타입
- SQLite 3.9.0+ 필수 (JSON1 extension)
- 프로젝트 최소 요구사항: Python 3.10+ (SQLite 3.37+ 포함)

### 성능 고려사항
- `citations` 컬럼은 인덱싱 불가 (JSON 타입)
- `sources_count`로 간단한 집계 쿼리 가능
- 복잡한 Citation 검색은 애플리케이션 레벨에서 처리

### 향후 개선 방안
- Alembic 마이그레이션 도구 도입 고려
- Citation 정규화 (별도 테이블) 검토
- 풀텍스트 검색 인덱스 추가
