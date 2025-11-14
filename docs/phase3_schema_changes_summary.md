# Phase 3: 데이터베이스 스키마 업데이트 - 변경 사항 요약

## 완료 날짜
2025-11-14

## 변경된 파일

### 1. `/app/models/documents.py`
**변경 유형**: 주석 추가 (필드 변경 없음)

**변경 내용**:
- `file_search_file_id` 필드에 주석 추가
  - `comment="FileSearchStore Document ID (documents/xxxxx 형식)"`
- `store_id` 필드에 주석 추가
  - `comment="FileSearchStore ID (fileSearchStores/xxxxx 형식)"`

**호환성**: ✅ **100% 하위 호환**
- 필드명, 타입, 제약조건 모두 동일
- 기존 데이터 마이그레이션 불필요

---

### 2. `/app/models/qa_logs.py`
**변경 유형**: 새 필드 추가

**추가된 필드**:
1. **citations** (JSON 타입)
   - Nullable: `True`
   - Comment: "Citation 정보 (출처 메타데이터)"
   - 용도: Gemini API 응답의 출처 정보 저장

2. **sources_count** (Integer 타입)
   - Default: `0`
   - Nullable: `False`
   - Comment: "검색된 소스 개수"
   - 용도: 검색 결과 집계 및 성능 모니터링

**호환성**: ✅ **100% 하위 호환**
- 모든 새 필드가 nullable 또는 기본값 제공
- 기존 레코드는 `citations=NULL`, `sources_count=0`으로 자동 처리

---

## 새로운 파일

### 1. `/docs/database_migration_guide.md`
**내용**: 상세한 마이그레이션 가이드
- 변경 사항 상세 설명
- 마이그레이션 방법 (개발/프로덕션)
- 호환성 보장 전략
- 검증 방법
- 롤백 절차

### 2. `/scripts/verify_schema_update.py`
**내용**: 스키마 검증 자동화 스크립트
- 테이블 구조 검증
- 필드 타입 및 제약조건 확인
- 모델 인스턴스 생성 테스트
- 레거시 호환성 테스트

---

## 기술적 결정 사항

### 1. 필드명 유지 결정
**선택**: 기존 필드명 유지 (`file_search_file_id`, `store_id`)
**이유**:
- 기존 코드와의 호환성 최대화
- 데이터 마이그레이션 불필요
- 주석으로 새 API 매핑 명확화 가능

**대안 (미채택)**:
- `vendor_document_id`, `vendor_store_id`로 변경
- 이유: 마이그레이션 복잡도 증가, 기존 코드 수정 범위 확대

---

### 2. Citations 저장 전략
**선택**: JSON 컬럼 사용
**이유**:
- Gemini API 응답 구조 유연하게 저장
- 정규화 없이 빠른 구현 가능
- SQLite JSON1 extension 활용

**제약사항**:
- JSON 컬럼은 인덱싱 불가
- 복잡한 검색은 애플리케이션 레벨에서 처리

**향후 개선**:
- Citation 사용 패턴 분석 후 정규화 고려
- 별도 `citations` 테이블 분리 검토

---

### 3. sources_count 추가
**선택**: 집계 필드 추가
**이유**:
- 검색 품질 모니터링 용이
- JSON 파싱 없이 빠른 통계 쿼리 가능
- 인덱싱 가능 (성능 최적화)

**사용 예시**:
```sql
-- 검색 결과가 없는 QA 로그 찾기
SELECT * FROM qa_logs WHERE sources_count = 0;

-- 평균 소스 개수
SELECT AVG(sources_count) FROM qa_logs;
```

---

## 검증 방법

### 자동 검증
```bash
# 스키마 검증 스크립트 실행
python scripts/verify_schema_update.py
```

**검증 항목**:
- ✅ Document 테이블 필드 존재 확인
- ✅ QALog 테이블 새 필드 확인
- ✅ 필드 타입 및 제약조건 검증
- ✅ 모델 인스턴스 생성 테스트
- ✅ 레거시 호환성 테스트

---

### 수동 검증
```bash
# SQLite CLI로 스키마 확인
sqlite3 data/elp.db

.schema documents
.schema qa_logs

# 데이터 무결성 확인
SELECT COUNT(*) FROM qa_logs;
SELECT COUNT(*) FROM documents;
```

---

## 마이그레이션 체크리스트

### 개발 환경
- [x] Document 모델 주석 추가
- [x] QALog 모델 필드 추가
- [x] 마이그레이션 가이드 작성
- [x] 검증 스크립트 작성
- [ ] 검증 스크립트 실행 및 확인
- [ ] Repository 레이어 업데이트 (Phase 4)

### 프로덕션 배포
- [ ] 데이터베이스 백업
- [ ] ALTER TABLE 스크립트 준비
- [ ] 롤백 계획 수립
- [ ] 배포 후 검증
- [ ] 모니터링 설정

---

## 다음 단계

### Phase 4: Repository 레이어 업데이트
**파일**:
- `/app/repositories/document_repository.py`
- `/app/repositories/qa_log_repository.py`

**작업 내용**:
1. Document Repository
   - `file_search_file_id` 업데이트 메서드 확인
   - `store_id` 저장 로직 검증

2. QA Log Repository
   - `citations` 저장 메서드 추가
   - `sources_count` 업데이트 로직 추가
   - 검색 쿼리 메서드 추가 (선택적)

---

## 참고 자료

### SQLAlchemy JSON 타입
- [SQLAlchemy JSON Types](https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.JSON)
- [SQLite JSON1 Extension](https://www.sqlite.org/json1.html)

### Gemini API Documentation
- [FileSearchStore API](https://ai.google.dev/gemini-api/docs/file-search)
- [Citation Metadata](https://ai.google.dev/gemini-api/docs/file-search#citation-metadata)

---

## 변경 이력

| 날짜 | 작업 | 담당자 | 비고 |
|------|------|--------|------|
| 2025-11-14 | Phase 3 완료 | AI Assistant | 스키마 업데이트 및 문서화 |
| 2025-11-14 | 검증 스크립트 작성 | AI Assistant | 자동화 검증 도구 |
