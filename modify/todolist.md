# QnA 챗봇 애플리케이션 리팩토링 작업 목록

## 문서 정보
- **작성일**: 2025-11-21
- **버전**: 1.0
- **기반 문서**: modify/plan.md
- **목적**: 실행 가능한 작업 단위로 분해하여 진행 상황 관리

---

## 진행 상황 요약

| Phase | 전체 작업 | 완료 | 진행 중 | 대기 | 진행률 |
|-------|-----------|------|---------|------|--------|
| Phase 1 | 4 | 4 | 0 | 0 | 100% ✅ |
| Phase 2 | 7 | 7 | 0 | 0 | 100% ✅ |
| Phase 3 | 3 | 1 | 0 | 2 | 33% 🔄 |
| Phase 4 | 6 | 0 | 0 | 6 | 0% |
| **전체** | **20** | **12** | **0** | **8** | **60%** |

---

## Phase 1: 새로운 스키마 및 디렉토리 구조 준비

### 우선순위: 🔴 High
### 예상 기간: 1주 (Week 1)

#### 작업 목록

- [x] **1.1 DB 테이블 생성** `#phase1` `#backend-dev` `#병렬가능` ✅
  - 파일: `app/models/chat_sessions.py` 생성 ✅
  - 파일: `app/models/chat_messages.py` 생성 ✅
  - Migration script 작성 (scripts/create_chat_tables.py) ✅
  - 테이블 생성 검증 ✅
  - 관계(relationship) 설정 검증 ✅
  - 인덱스 생성 검증 ✅
  - **담당**: backend-dev
  - **예상 시간**: 4시간
  - **완료 시간**: 2025-11-21 22:43

- [x] **1.2 디렉토리 구조 생성** `#phase1` `#infra` `#병렬가능` ✅
  - `data/lessonplan/` 디렉토리 생성 ✅
  - `data/analys/` 디렉토리 생성 ✅
  - `prompt/` 디렉토리 생성 ✅
  - `prompt/prompt.md` 템플릿 파일 작성 ✅
  - 디렉토리 권한 설정 (읽기/쓰기) ✅
  - **담당**: infra
  - **예상 시간**: 1시간
  - **완료 시간**: 2025-11-21 22:44

- [x] **1.3 FileSearchService 구현** `#phase1` `#backend-dev` `#병렬가능` `#핵심` ✅
  - 파일: `app/services/file_search_service.py` (기존 존재) ✅
  - `search_in_store()` 메서드 구현 ✅
  - `upload_to_store()` 메서드 (기존 upload_document로 존재) ✅
  - `_extract_citations()` 메서드 구현 ✅
  - 업로드 polling 동작 검증 ✅
  - metadata_filter 구문 검증 ✅
  - 타임아웃 처리 구현 (5분) ✅
  - 단위 테스트 작성 (scripts/test_file_search_service.py) ✅
  - **담당**: backend-dev
  - **예상 시간**: 8시간
  - **완료 시간**: 2025-11-21 22:48
  - **참조**: Research/file_search_api_guide.md

- [x] **1.4 통합 테스트 환경 구성** `#phase1` `#qa` ✅
  - 테스트 데이터베이스 설정 ✅
  - 테스트용 Vector DB Store 생성 ✅
  - DB 연결 확인 ✅
  - Vector DB 접근 확인 ✅
  - 통합 테스트 스크립트 작성 (scripts/setup_test_env.py) ✅
  - **담당**: qa
  - **예상 시간**: 2시간
  - **완료 시간**: 2025-11-21 22:49

#### Phase 1 검증 기준
- [x] chat_sessions, chat_messages 테이블이 생성됨 ✅
- [x] 디렉토리 구조가 준비됨 ✅
- [x] FileSearchService가 구현되고 기본 동작 확인됨 ✅
- [x] 통합 테스트 환경이 구성됨 ✅

---

## Phase 2: 서비스 레이어 리팩토링

### 우선순위: 🔴 High
### 예상 기간: 1주 (Week 2)
### 상태: 🟢 진행 중

#### 작업 목록

- [x] **2.1 LessonPlanStorageService 구현** `#phase2` `#backend-dev` `#병렬가능` ✅
  - 파일: `app/services/lessonplan_storage_service.py` 생성 ✅
  - `save_lessonplan()` 메서드 구현 ✅
  - `get_lessonplan_path()` 메서드 구현 ✅
  - `list_lessonplans()` 메서드 구현 ✅
  - `delete_lessonplan()` 메서드 구현 ✅
  - 파일명 규칙 검증 (`{username}_{원본파일명}`) ✅
  - 파일 저장/조회/삭제 동작 검증 ✅
  - 단위 테스트 작성 ✅
  - **담당**: backend-dev
  - **예상 시간**: 4시간
  - **완료 시간**: 2025-11-21 23:15

- [x] **2.2 AnalysisStorageService 구현** `#phase2` `#backend-dev` `#병렬가능` ✅
  - 파일: `app/services/analysis_storage_service.py` 생성 ✅
  - `save_analysis()` 메서드 구현 ✅
  - `_generate_markdown_header()` 메서드 구현 ✅
  - `get_analysis()` 메서드 구현 ✅
  - `list_analyses()` 메서드 구현 ✅
  - `delete_analysis()` 메서드 구현 ✅
  - 마크다운 헤더 자동 생성 검증 ✅
  - 파일명 규칙 검증 ✅
  - 단위 테스트 작성 ✅
  - **담당**: backend-dev
  - **예상 시간**: 4시간
  - **완료 시간**: 2025-11-21 23:25

- [x] **2.3 CriteriaVectorService 구현** `#phase2` `#backend-dev` `#병렬가능` `#핵심` ✅
  - 파일: `app/services/criteria_vector_service.py` 생성 ✅
  - `upload_criteria()` 메서드 구현 ✅
  - `delete_criteria()` 메서드 구현 ✅
  - `delete_all_criteria()` 메서드 구현 ✅
  - `_recreate_criteria_store()` 메서드 구현 ✅
  - `search_criteria()` 메서드 구현 ✅
  - Store 재생성 동작 검증 ✅
  - metadata_filter 구문 검증 (`'type=\"criteria\"'`) ✅
  - 새 업로드 시 기존 삭제 동작 검증 ✅
  - 단위 테스트 작성 ✅
  - **담당**: backend-dev
  - **예상 시간**: 6시간
  - **완료 시간**: 2025-11-21 23:50

- [x] **2.4 LessonPlanVectorService 구현** `#phase2` `#backend-dev` `#병렬가능` `#핵심` ✅
  - 파일: `app/services/lessonplan_vector_service.py` 생성 ✅
  - `upload_temporary()` 메서드 구현 ✅
  - `delete_on_logout()` 메서드 구현 ✅
  - `delete_on_session_close()` 메서드 구현 ✅
  - `delete_user_documents()` 메서드 구현 ✅
  - `_delete_user_store()` 메서드 구현 ✅
  - `_delete_store()` 메서드 구현 ✅
  - `cleanup_expired_sessions()` 메서드 구현 ✅
  - `list_user_documents()` 메서드 구현 ✅
  - 세션 종료 시 Store 삭제 검증 ✅
  - custom_metadata 저장 검증 ✅
  - 단위 테스트 작성 ✅
  - 모든 테스트 통과 (9/9) ✅
  - **담당**: backend-dev
  - **예상 시간**: 6시간
  - **완료 시간**: 2025-11-21 23:59

- [x] **2.5 PromptLoaderService 구현** `#phase2` `#backend-dev` `#병렬가능` ✅
  - 파일: `app/services/prompt_loader_service.py` 생성 ✅
  - 파일: `prompt/prompt.md` 초기 내용 작성 ✅ (기존 존재)
  - `get_prompt()` 메서드 구현 (캐싱 포함) ✅
  - `_extract_prompt()` 메서드 구현 ✅
  - `reload_cache()` 메서드 구현 ✅
  - `list_available_prompts()` 메서드 구현 ✅
  - 프롬프트 타입별 로드 검증 ✅
  - 캐싱 메커니즘 동작 확인 ✅
  - 단위 테스트 작성 ✅
  - **담당**: backend-dev
  - **예상 시간**: 4시간
  - **완료 시간**: 2025-11-21 23:35

- [x] **2.6 QnAService 리팩토링** `#phase2` `#backend-dev` `#순차실행` ✅
  - `ask_question()` 메서드 재작성 ✅
  - session_id 기반으로 변경 ✅
  - PromptLoaderService로 프롬프트 로드 ✅
  - FileSearchService 사용 ✅
  - chat_messages 테이블에 메시지 저장 ✅
  - 대화 히스토리 조회 로직 구현 ✅
  - 세션 기반 QnA 동작 검증 ✅
  - 통합 테스트 작성 ✅
  - **담당**: backend-dev
  - **예상 시간**: 6시간
  - **완료 시간**: 2025-11-21 23:XX
  - **의존성**: Task 2.1, 2.4, 2.5 완료 필요

- [x] **2.7 EvalService 리팩토링** `#phase2` `#backend-dev` `#순차실행` ✅
  - 평가 결과를 AnalysisStorageService로 저장 ✅
  - CriteriaVectorService로 평가기준 검색 ✅
  - 평가 로직 재작성 ✅
  - 평가 결과 마크다운 저장 검증 ✅
  - 평가기준 검색 동작 검증 ✅
  - 통합 테스트 작성 ✅
  - **담당**: backend-dev
  - **예상 시간**: 6시간
  - **완료 시간**: 2025-11-21 23:XX
  - **의존성**: Task 2.2, 2.3 완료 필요

#### Phase 2 검증 기준
- [x] 모든 Storage 서비스가 구현됨 ✅
- [x] Vector 서비스가 구현됨 ✅
- [x] PromptLoader가 구현되고 프롬프트 로드 확인됨 ✅
- [x] QnAService, EvalService가 리팩토링됨 ✅
- [x] 단위 테스트 통과 ✅

---

## Phase 3: 데이터 마이그레이션

### 우선순위: 🟠 Medium
### 예상 기간: 1주 (Week 3)
### 상태: 🟢 진행 중

#### 작업 목록

- [x] **3.1 DB 백업** `#phase3` `#backend-dev` `#순차실행` `#필수` ✅
  - 전체 DB 백업 수행 ✅
  - 백업 파일 생성: `backup/db_backup_20251121_232324.db` ✅
  - 백업 검증 스크립트 작성 및 실행 ✅
  - 백업 무결성 확인 ✅
  - **담당**: backend-dev
  - **예상 시간**: 1시간
  - **완료 시간**: 2025-11-21 23:23
  - **⚠️ 주의**: 마이그레이션 전 필수 작업

- [ ] **3.2 마이그레이션 스크립트 작성 및 실행** `#phase3` `#backend-dev` `#순차실행` `#핵심`
  - 파일: `scripts/migrate_to_chat_sessions.py` 작성
    - qa_logs 데이터 그룹핑 (document_id, user_id)
    - chat_sessions 생성
    - 질문/답변을 chat_messages로 변환
  - 파일: `scripts/migrate_documents_to_files.py` 작성
    - documents 메타데이터를 lessonplan/ 폴더로 이동
  - 파일: `scripts/migrate_evaluations_to_markdown.py` 작성
    - evaluations를 analys/*.md로 변환
  - 파일: `scripts/migrate_prompts_to_file.py` 작성
    - system_prompts를 prompt/prompt.md로 이동
  - 모든 스크립트 실행
  - 데이터 count 검증
  - 샘플 데이터 검증
  - **담당**: backend-dev
  - **예상 시간**: 12시간
  - **의존성**: Task 3.1 완료 필요

- [ ] **3.3 마이그레이션 검증** `#phase3` `#qa` `#병렬가능`
  - chat_sessions 개수 확인
  - chat_messages 개수 확인 (qa_logs * 2)
  - 파일 시스템 파일 개수 확인
  - 샘플 데이터 무결성 확인
  - 검증 리포트 작성
  - **담당**: qa
  - **예상 시간**: 4시간

#### Phase 3 검증 기준
- [x] DB 백업 완료 ✅
- [ ] 모든 마이그레이션 스크립트 실행 완료
- [ ] 데이터 일치성 검증 완료
- [ ] 샘플 데이터로 기능 동작 확인

---

## Phase 4: 레거시 제거 및 검증

### 우선순위: 🟡 Low (검증 완료 후)
### 예상 기간: 1주 (Week 4)

#### 작업 목록

- [ ] **4.1 기존 테이블 제거** `#phase4` `#backend-dev` `#순차실행`
  - 파일: `scripts/drop_old_tables.py` 작성
  - Alembic migration script 작성
  - 테이블 삭제:
    - `documents`
    - `evaluations`
    - `criteria`
    - `qa_logs`
    - `system_prompts`
  - 테이블 삭제 검증
  - 애플리케이션 정상 동작 확인
  - **담당**: backend-dev
  - **예상 시간**: 2시간

- [ ] **4.2 레거시 코드 제거** `#phase4` `#backend-dev` `#순차실행`
  - `app/models/` 하위 사용하지 않는 모델 제거
  - 직접 파일 시스템 탐색 코드 제거
  - 직접 Gemini API 호출 코드 제거
  - 사용하지 않는 import 제거
  - 린트 실행 및 에러 수정
  - **담당**: backend-dev
  - **예상 시간**: 4시간
  - **의존성**: Task 4.1 완료 필요

- [ ] **4.3 통합 테스트** `#phase4` `#qa` `#병렬가능` `#핵심`
  - 테스트 시나리오 1: 지도안 업로드 → QnA → 분석 → 결과 저장
  - 테스트 시나리오 2: 평가기준 업로드 → 분석 → Store 삭제
  - 테스트 시나리오 3: 세션 종료 → 임시 지도안 삭제
  - 테스트 시나리오 4: 프롬프트 로드 → QnA
  - 모든 시나리오 통과 검증
  - 에러 없음 확인
  - 테스트 리포트 작성
  - **담당**: qa
  - **예상 시간**: 8시간

- [ ] **4.4 성능 테스트** `#phase4` `#qa` `#병렬가능`
  - 동시 사용자 10명 QnA 테스트
  - 대용량 파일 업로드 테스트 (50MB)
  - 응답 시간 측정 및 분석
  - 에러율 측정 (<1% 목표)
  - 성능 리포트 작성
  - **담당**: qa
  - **예상 시간**: 6시간

- [ ] **4.5 문서화** `#phase4` `#backend-dev` `#병렬가능`
  - API 문서 업데이트
  - 배포 가이드 작성
  - 롤백 절차서 작성
  - 모든 문서 최신 상태 확인
  - **담당**: backend-dev
  - **예상 시간**: 4시간

- [ ] **4.6 배포** `#phase4` `#devops` `#순차실행` `#필수`
  - Staging 환경 배포
  - Staging 검증
  - Production DB 백업
  - Production 배포
  - 모니터링 설정
  - 배포 성공 확인
  - 에러율 확인
  - **담당**: devops
  - **예상 시간**: 4시간
  - **의존성**: Task 4.3, 4.4, 4.5 완료 필요

#### Phase 4 검증 기준
- [ ] 레거시 테이블 및 코드 제거 완료
- [ ] 통합 테스트 통과
- [ ] 성능 테스트 통과
- [ ] 문서화 완료
- [ ] 프로덕션 배포 완료

---

## 롤백 계획

### 긴급 롤백 시나리오

각 Phase별로 롤백 스크립트를 준비합니다:

- [ ] **롤백 스크립트 작성** `#rollback` `#backend-dev`
  - 파일: `scripts/rollback_migration.py` 작성
  - Phase별 롤백 로직 구현
  - 백업 DB 복원 로직
  - 새 테이블 삭제 로직
  - 롤백 스크립트 테스트
  - **담당**: backend-dev
  - **예상 시간**: 4시간

### 롤백 절차
```bash
# Phase 3 롤백 예시
python scripts/rollback_migration.py --phase 3
cp backup/db_backup_{timestamp}.db data/app.db
# 애플리케이션 재시작
```

---

## 일정 및 마일스톤

| 주차 | Phase | 시작일 | 종료일 | 상태 |
|------|-------|--------|--------|------|
| Week 1 | Phase 1 | 2025-11-25 | 2025-11-29 | 🔵 대기 |
| Week 2 | Phase 2 | 2025-12-02 | 2025-12-06 | 🔵 대기 |
| Week 3 | Phase 3 | 2025-12-09 | 2025-12-13 | 🔵 대기 |
| Week 4 | Phase 4 | 2025-12-16 | 2025-12-20 | 🔵 대기 |

---

## 우선순위 가이드

- 🔴 **High**: 즉시 시작, 프로젝트 핵심
- 🟠 **Medium**: 계획된 시점에 시작
- 🟡 **Low**: 다른 작업 완료 후 진행

---

## 태그 설명

- `#phase1` ~ `#phase4`: Phase 번호
- `#backend-dev`: Backend 개발자 담당
- `#frontend-dev`: Frontend 개발자 담당
- `#infra`: 인프라 담당
- `#qa`: QA 담당
- `#devops`: DevOps 담당
- `#병렬가능`: 다른 작업과 병렬 실행 가능
- `#순차실행`: 의존성이 있어 순차 실행 필요
- `#핵심`: 프로젝트 핵심 작업
- `#필수`: 반드시 수행해야 하는 작업
- `#rollback`: 롤백 관련 작업

---

## 참조 문서
- modify/plan.md: 상세 실행 계획
- modify/refactor.md: 리팩토링 설계 문서
- Research/file_search_api_guide.md: Gemini File Search API 가이드

---

**작성자**: Claude Code
**작성일**: 2025-11-21
**버전**: 1.0
