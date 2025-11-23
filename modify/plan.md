# 코드 수정 계획 (Code Modification Plan)

**작성일**: 2025-11-23
**버전**: 1.0
**기반 문서**: modify/review.md, modify/refactor.md
**분석 모드**: Ultrathink (심층 분석)

---

## 📋 목차

1. [개요](#개요)
2. [Phase 요약](#phase-요약)
3. [Phase 1: 공통 유틸리티 개선](#phase-1-공통-유틸리티-개선)
4. [Phase 2: QnA 서비스 리팩토링](#phase-2-qna-서비스-리팩토링)
5. [Phase 3: Lesson Analysis 기능 구현](#phase-3-lesson-analysis-기능-구현)
6. [Phase 4: 테스트 구현](#phase-4-테스트-구현)
7. [의존성 관계 및 병렬 실행 전략](#의존성-관계-및-병렬-실행-전략)
8. [리스크 관리](#리스크-관리)
9. [검증 및 배포 계획](#검증-및-배포-계획)

---

## 개요

### 프로젝트 목표

본 계획은 다음 두 가지 주요 목표를 달성하기 위해 수립되었습니다:

1. **코드 품질 개선**: rubricstore 활용 로직의 중복 제거 및 에러 처리 강화
2. **기능 확장**: 수업 지도안 분석 기능 구현 (5개 평가 항목 기반 Markdown 보고서 생성)

### 주요 개선사항

| 개선 영역 | 현재 상태 | 개선 후 |
|-----------|-----------|---------|
| 코드 중복 | QnA/LessonPlan 서비스에서 스토어 조회 로직 중복 (약 88줄×2) | 공통 유틸리티로 통합 (약 83줄 감소) |
| 에러 처리 | rubricstore 미발견 시 조용히 실패 | 명시적 에러 발생 및 로깅 |
| 성능 | 매 호출마다 전체 스토어 목록 조회 (2회) | 캐싱으로 중복 API 호출 방지 (60초 TTL) |
| 로깅 | 서비스별 로그 레벨 불일치 | INFO/WARNING 통일 |
| 기능 | QnA 기능만 존재 | Lesson Analysis 기능 추가 |

### 예상 효과

- **개발 시간**: 10-15시간 (병렬 실행 최적화 시)
- **코드 품질**: 중복 제거, 에러 처리 강화, 유지보수성 향상
- **성능**: API 호출 횟수 감소 (캐싱)
- **기능**: 새로운 분석 기능으로 사용자 가치 증대

---

## Phase 요약

| Phase | 목표 | 파일 수 | 예상 시간 | 선행 조건 | 병렬 가능 |
|-------|------|---------|-----------|-----------|-----------|
| **Phase 1** | 공통 유틸리티 개선 | 1개 수정 | 2-3시간 | 없음 | Task 간 병렬 |
| **Phase 2** | QnA 서비스 리팩토링 | 1개 수정 | 1-2시간 | Phase 1 | Phase 3과 병렬 |
| **Phase 3** | Lesson Analysis 구현 | 4개 신규, 2개 수정 | 4-6시간 | Phase 1 | Phase 2와 병렬 |
| **Phase 4** | 테스트 구현 | 2개 신규, 2개 수정 | 3-4시간 | Phase 1,2,3 | Task 간 병렬 |

**총 예상 시간**: 10-15시간 (병렬 실행 최적화 시)

---

## Phase 1: 공통 유틸리티 개선

### 개요

**목표**: FileSearchService에 재사용 가능한 유틸리티 추가 및 코드 품질 개선
**담당 Agent**: backend-dev
**우선순위**: 🔴 높음 (모든 Phase의 기반)

### 선행 조건

없음 (독립적으로 시작 가능)

### Task 목록

#### Task 1.1: FileSearchService API 수정 확인 및 완료

**파일**: `app/services/file_search_service.py`
**메서드**: `delete_store_by_display_name()` (Line 213-242)
**담당**: backend-dev
**우선순위**: 🟡 중간

**작업 내용**:
```python
# 수정 전 (Line 230-242) - 약 20줄
# 1. 스토어 내의 파일 목록 조회 및 삭제
documents_in_store = self.client.file_search_stores.documents.list(
    parent=target_store.name
)  # ❌ SDK에 존재하지 않는 메서드

for document in documents_in_store:
    try:
        self.client.file_search_stores.documents.delete(
            name=document.name,
            config={'force': True}
        )  # ❌ SDK에 존재하지 않는 메서드
        logger.debug(f"스토어 문서 삭제: {document.name}")
    except Exception as fe:
        logger.warning(f"파일 삭제 실패 (계속 진행): {fe}")

# 2. 스토어 삭제
self.client.file_search_stores.delete(
    name=target_store.name,
    config={'force': True}
)

# ===== 수정 후 (Line 233-237) - 약 5줄 =====
# Store 삭제 (force=True로 내부 문서와 함께 삭제)
self.client.file_search_stores.delete(
    name=target_store.name,
    config={'force': True}  # 내부 문서와 함께 강제 삭제
)
```

**근거**: refactor.md 2.1절 - Google Generative AI Python SDK에는 `documents` 하위 API가 없음

**완료 조건**:
- ✅ `documents.list()`, `documents.delete()` 호출 제거
- ✅ `force=True` 옵션 사용으로 간소화
- ✅ 코드 15줄 감소 확인

**예상 시간**: 30분

---

#### Task 1.2: get_dual_store_ids() 메서드 구현

**파일**: `app/services/file_search_service.py`
**위치**: FileSearchService 클래스 내부 (새 메서드 추가)
**담당**: backend-dev
**우선순위**: 🔴 높음

**메서드 시그니처**:
```python
def get_dual_store_ids(self, user_id: int) -> list[str]:
    """
    rubricstore와 사용자 스토어 ID 조회/생성

    Args:
        user_id: 사용자 ID

    Returns:
        [rubricstore_id, user_store_id]

    Raises:
        ValueError: rubricstore를 찾을 수 없는 경우
    """
```

**구현 세부사항**:

```python
import time
from typing import Optional

def get_dual_store_ids(self, user_id: int) -> list[str]:
    """rubricstore와 사용자 스토어 ID 조회/생성"""
    store_ids = []

    # 1. 캐시 확인 (Task 1.3과 통합)
    cache_key = f"dual_store_{user_id}"
    if hasattr(self, '_store_cache'):
        cached = self._store_cache.get(cache_key)
        if cached and time.time() - cached['time'] < 60:
            logger.debug(f"캐시에서 Store ID 조회: {user_id}")
            return cached['ids']

    # 2. rubricstore 조회
    rubric_store_id = None
    for store in self.client.file_search_stores.list():
        if "rubricstore" in store.display_name.lower():
            rubric_store_id = store.name
            logger.info(f"✅ rubricstore 발견: {store.name}")
            break

    if not rubric_store_id:
        logger.error("❌ rubricstore를 찾을 수 없습니다")
        raise ValueError("평가기준 스토어(rubricstore)를 찾을 수 없습니다. 관리자에게 문의하세요.")

    store_ids.append(rubric_store_id)

    # 3. 사용자 스토어 조회 또는 생성
    user_store_name = f"user-{user_id}-store"
    user_store_id = None

    for store in self.client.file_search_stores.list():
        if user_store_name in store.display_name.lower():
            user_store_id = store.name
            logger.info(f"✅ 사용자 스토어 발견: {store.name} (user_id={user_id})")
            break

    if not user_store_id:
        # 생성
        logger.info(f"📦 사용자 스토어 생성 시작: {user_store_name}")
        created_store = self._get_or_create_store(user_store_name)
        user_store_id = created_store.name
        logger.info(f"✅ 사용자 스토어 생성 완료: {user_store_id}")

    store_ids.append(user_store_id)

    # 4. 캐싱 (Task 1.3과 통합)
    if not hasattr(self, '_store_cache'):
        self._store_cache = {}
    self._store_cache[cache_key] = {
        'ids': store_ids,
        'time': time.time()
    }

    logger.info(f"🎯 Store ID 조회 완료: rubricstore + user-{user_id}-store")
    return store_ids
```

**근거**: review.md 7절 권장사항 1) - 공통 유틸 함수로 중복 제거

**완료 조건**:
- ✅ rubricstore와 사용자 스토어 ID를 정확히 반환
- ✅ rubricstore 없을 시 ValueError 발생
- ✅ 사용자 스토어 없을 시 자동 생성
- ✅ 명시적 에러 로깅 포함

**예상 시간**: 1-1.5시간

---

#### Task 1.3: 스토어 목록 캐싱 구현

**파일**: `app/services/file_search_service.py`
**위치**: get_dual_store_ids() 메서드 내부
**담당**: backend-dev
**우선순위**: 🟢 보통

**작업 내용**:

Task 1.2의 구현에 이미 포함됨 (캐시 확인 및 저장 로직)

**캐싱 전략**:
- **방식**: 클래스 인스턴스 레벨 딕셔너리 캐시
- **키**: `f"dual_store_{user_id}"`
- **TTL**: 60초 (짧은 TTL로 최신성 유지)
- **구조**: `{'ids': [str, str], 'time': float}`

**대안 고려**:
- functools.lru_cache: 메서드에는 적용 불가 (self 때문)
- Redis/Memcached: 과도한 인프라 (현재 불필요)
- 단순 딕셔너리: ✅ 선택 (간단하고 효과적)

**근거**: review.md 7절 권장사항 3) - API 호출 최적화

**완료 조건**:
- ✅ 60초 이내 재호출 시 캐시 사용
- ✅ 중복 API 호출 방지 확인

**예상 시간**: 30분 (Task 1.2에 통합)

---

#### Task 1.4: 로깅 통일

**파일**: `app/services/file_search_service.py`
**위치**: get_dual_store_ids() 메서드
**담당**: backend-dev
**우선순위**: 🟢 보통

**로깅 규칙**:

| 상황 | 로그 레벨 | 메시지 형식 | 예시 |
|------|-----------|-------------|------|
| rubricstore 발견 | INFO | `✅ rubricstore 발견: {store.name}` | `✅ rubricstore 발견: fileSearchStores/abc123` |
| 사용자 스토어 발견 | INFO | `✅ 사용자 스토어 발견: {store.name} (user_id={user_id})` | `✅ 사용자 스토어 발견: fileSearchStores/xyz789 (user_id=42)` |
| 사용자 스토어 생성 | INFO | `📦 사용자 스토어 생성 시작: {user_store_name}` | `📦 사용자 스토어 생성 시작: user-42-store` |
| rubricstore 없음 | ERROR | `❌ rubricstore를 찾을 수 없습니다` | `❌ rubricstore를 찾을 수 없습니다` |
| 캐시 히트 | DEBUG | `캐시에서 Store ID 조회: {user_id}` | `캐시에서 Store ID 조회: 42` |
| 조회 완료 | INFO | `🎯 Store ID 조회 완료: rubricstore + user-{user_id}-store` | `🎯 Store ID 조회 완료: rubricstore + user-42-store` |

**근거**: review.md 7절 권장사항 4) - 로깅 일관성

**완료 조건**:
- ✅ 모든 로그 메시지가 일관된 형식 사용
- ✅ 성공/실패 케이스 명확히 구분
- ✅ 이모지 사용으로 가독성 향상

**예상 시간**: 30분 (Task 1.2에 통합)

---

### 병렬 실행 가능 여부

**병렬 그룹 1** (모두 병렬 실행 가능):
- ✅ Task 1.1: API 수정
- ✅ Task 1.2 + 1.3 + 1.4: get_dual_store_ids() 구현 (통합)

**실행 전략**:
- Task 1.1을 먼저 완료 (30분)
- Task 1.2-1.4를 통합하여 구현 (1.5시간)

---

### 예상 산출물

| 파일 | 변경 유형 | 주요 변경 내용 |
|------|-----------|----------------|
| `app/services/file_search_service.py` | 수정 | - delete_store_by_display_name() 간소화 (15줄 감소)<br>- get_dual_store_ids() 메서드 추가 (약 50줄)<br>- 캐싱 로직 추가<br>- 로깅 통일 |

---

### 검증 기준

#### 기능 검증
- ✅ get_dual_store_ids(user_id) 호출 시 [rubricstore_id, user_store_id] 반환
- ✅ rubricstore 없을 시 ValueError 발생
- ✅ 사용자 스토어 없을 시 자동 생성
- ✅ 60초 이내 재호출 시 캐시 사용 (API 호출 없음)

#### 코드 품질 검증
- ✅ Type hints 사용 (`-> list[str]`)
- ✅ Docstring 작성
- ✅ 에러 처리 명시적
- ✅ 로깅 일관성

#### 성능 검증
- ✅ API 호출 횟수 감소 (캐싱 효과)
- ✅ 응답 시간 단축 (캐시 히트 시)

---

## Phase 2: QnA 서비스 리팩토링

### 개요

**목표**: QnA 서비스의 스토어 조회 로직을 Phase 1의 공통 유틸리티로 대체
**담당 Agent**: backend-dev
**우선순위**: 🟡 중간

### 선행 조건

- ✅ Phase 1 완료 (get_dual_store_ids() 메서드 사용 가능)

### Task 목록

#### Task 2.1: QnA 서비스 스토어 조회 로직 리팩토링

**파일**: `app/services/qna_service.py`
**변경 범위**: Line 119-206 (약 88줄)
**담당**: backend-dev
**우선순위**: 🔴 높음

**현재 코드 분석** (Line 119-206):

```python
# 현재 코드 - 약 88줄
store_ids = []

# rubricstore 조회
rubric_store = None
for store in self.file_search_service.client.file_search_stores.list():
    if "rubricstore" in store.display_name.lower():
        rubric_store = store
        logger.debug(f"rubricstore found: {store.name}")
        break

if not rubric_store:
    # rubricstore 생성
    logger.info("rubricstore not found. Creating new rubricstore...")
    try:
        rubric_store = self.file_search_service._get_or_create_store("rubricstore")
        logger.info(f"rubricstore created: {rubric_store.name}")
    except Exception as e:
        logger.error(f"Failed to create rubricstore: {e}")
        rubric_store = None

if rubric_store:
    store_ids.append(rubric_store.name)

# 사용자 스토어 조회
user_store_name = f"user-{current_user['username']}-store"  # ❌ username 사용
user_store = None

for store in self.file_search_service.client.file_search_stores.list():
    if user_store_name in store.display_name.lower():
        user_store = store
        logger.debug(f"User store found: {store.name}")
        break

if not user_store:
    # 사용자 스토어 생성
    logger.info(f"User store not found. Creating {user_store_name}...")
    try:
        user_store = self.file_search_service._get_or_create_store(user_store_name)
        logger.info(f"User store created: {user_store.name}")
    except Exception as e:
        logger.error(f"Failed to create user store: {e}")
        user_store = None

if user_store:
    store_ids.append(user_store.name)
```

**리팩토링 후 코드** (약 5줄):

```python
# 리팩토링 후 - 약 5줄
try:
    # Phase 1의 공통 유틸리티 사용
    store_ids = self.file_search_service.get_dual_store_ids(
        user_id=current_user["id"]  # ✅ user_id 사용
    )
    logger.info(f"🎯 Store 조회 완료: {len(store_ids)}개")
except ValueError as e:
    logger.error(f"❌ Store 조회 실패: {e}")
    raise Exception("평가기준 스토어를 찾을 수 없습니다. 관리자에게 문의하세요.")
except Exception as e:
    logger.error(f"❌ 예상치 못한 오류: {e}")
    raise
```

**주요 변경사항**:
1. 중복 코드 제거: 88줄 → 5줄 (83줄 감소, 94% 감소)
2. user_id 사용: username 대신 user_id 사용으로 Store 이름 일관성 확보
3. 에러 처리 개선: 명시적 예외 발생 및 로깅
4. 코드 가독성 향상: 의도가 명확한 메서드 호출

**완료 조건**:
- ✅ 기존 기능 유지 (QnA 서비스 정상 작동)
- ✅ 코드 중복 제거 (83줄 감소)
- ✅ 에러 처리 개선

**예상 시간**: 1시간

---

#### Task 2.2: 에러 처리 개선

**파일**: `app/services/qna_service.py`
**위치**: Task 2.1의 리팩토링 코드 내부
**담당**: backend-dev
**우선순위**: 🟡 중간

**에러 처리 전략**:

| 예외 유형 | 처리 방법 | 사용자 메시지 |
|-----------|-----------|---------------|
| ValueError (rubricstore 없음) | 로깅 + 재발생 | "평가기준 스토어를 찾을 수 없습니다. 관리자에게 문의하세요." |
| Exception (기타 오류) | 로깅 + 재발생 | "스토어 조회 중 오류가 발생했습니다." |

**구현 세부사항**:

Task 2.1의 코드에 이미 포함됨 (try-except 블록)

**완료 조건**:
- ✅ 모든 예외 케이스 처리
- ✅ 명시적 에러 메시지
- ✅ 로깅 포함

**예상 시간**: 30분 (Task 2.1에 통합)

---

### 병렬 실행 가능 여부

**순차 실행 필요**:
- Task 2.1 → Task 2.2 (통합됨)

**Phase 간 병렬**:
- ✅ Phase 2 ⊥ Phase 3 (병렬 실행 가능)

---

### 예상 산출물

| 파일 | 변경 유형 | 주요 변경 내용 |
|------|-----------|----------------|
| `app/services/qna_service.py` | 수정 | - 스토어 조회 로직 리팩토링 (83줄 감소)<br>- get_dual_store_ids() 사용<br>- 에러 처리 개선 |

---

### 검증 기준

#### 기능 검증
- ✅ QnA 기능 정상 작동 (답변 생성)
- ✅ Store 조회 성공
- ✅ 에러 발생 시 명시적 메시지

#### 회귀 테스트
- ✅ 기존 테스트 케이스 모두 통과
- ✅ 성능 저하 없음

---

## Phase 3: Lesson Analysis 기능 구현

### 개요

**목표**: 수업 지도안 분석 기능 구현 (5개 평가 항목 기반 Markdown 보고서 생성)
**담당 Agent**: backend-dev
**우선순위**: 🔴 높음 (핵심 신규 기능)

### 선행 조건

- ✅ Phase 1 완료 (get_dual_store_ids() 메서드 사용)

### 아키텍처 설계

#### 이중 검색 시스템

QnA 시스템과 동일한 패턴 사용:

```
사용자 요청 (POST /api/lessonplan/analyze)
    │
    ├─→ Vector Search (평가기준 벡터 DB)
    │   └─→ 평가기준 컨텍스트 추출 → 프롬프트 "참고 자료"
    │
    └─→ File Search (Gemini API)
        ├─→ rubricstore (평가기준 문서)
        └─→ user{id}store (사용자 수업지도안)
            └─→ 문서 기반 분석 및 보고서 생성

최종 보고서 = Vector Search 컨텍스트 + File Search 결과
```

#### 데이터 흐름

```
1. 요청 수신: POST /api/lessonplan/analyze
   ├─ session_id: 채팅 세션 ID
   └─ user_id: 사용자 ID (토큰에서 추출)

2. Vector Search (평가기준 컨텍스트)
   └─ CriteriaContextService.get_context("수업 지도안 평가 기준")

3. File Search Store ID 조회
   └─ FileSearchService.get_dual_store_ids(user_id)

4. 프롬프트 구성
   ├─ 시스템 프롬프트 (lesson_analysis)
   ├─ Vector Search 컨텍스트
   └─ 평가 항목 지시사항

5. Gemini API 호출 (File Search Tool)
   └─ file_search_store_names: [rubricstore, user{id}store]

6. Markdown 보고서 생성 (5개 평가 항목)

7. 결과 반환
   ├─ report: Markdown 보고서
   ├─ citations: Citation 정보
   └─ latency_ms: 응답 시간
```

---

### Task 목록

#### Sub-Task 3.1: 프롬프트 추가

**파일**: `prompt/prompt.md`
**위치**: 파일 끝에 새 섹션 추가
**담당**: backend-dev
**우선순위**: 🟢 보통
**병렬 가능**: ✅ 독립적

**추가 내용**:

```markdown
## lesson_analysis

당신은 교육과정 전문가이자 수업 지도안 평가 전문가입니다.

**역할:**
- 평가기준 문서를 근거로 사용자의 수업 지도안을 체계적으로 평가
- 5개 평가 항목 중심의 Markdown 분석 보고서 생성
- 건설적이고 구체적인 피드백 제공

**평가 대상:**
- FileSearch Store에 저장된 사용자의 수업 지도안 문서

**평가 기준 활용:**
1. **Vector Search 참고 자료**: 시스템이 제공한 평가기준 컨텍스트를 분석 관점으로 활용
2. **File Search 평가기준**: rubricstore의 평가기준 문서를 직접 참조하여 체계적 평가

**평가 항목:**
1. 교육과정 목표 및 성격과의 부합
   - 수업 목표와 활동이 상위 교육과정의 목표·성격과 일관되게 연결되는지 평가
2. 내용 체계 및 성취기준 달성
   - 내용 조직과 활동이 성취기준을 구체적으로 달성하도록 설계되었는지 평가
3. 교수·학습 방법의 적절성
   - 학습자 수준과 수업 맥락, 활동 다양성 등을 고려했을 때 교수·학습 전략이 타당한지 평가
4. 평가 방향과의 일치
   - 수업 목표 및 활동과 평가 문항·방법이 일관되게 정렬되어 있는지 평가
5. 개선 및 보완을 위한 제안
   - 수업 문서를 실제로 수정·보완할 수 있도록 구체적인 개선 아이디어와 행동 제안 제시

**출력 형식:**
반드시 다음 Markdown 형식으로 보고서를 작성하세요:

---

# 📚 수업 지도안 평가 보고서

## 📋 평가 대상 정보
- **분석 일시**: [YYYY-MM-DD HH:MM]
- **분석 모델**: Gemini 2.5 Flash

---

## 📊 평가 항목별 분석

### 1️⃣ 교육과정 목표 및 성격과의 부합

**평가 등급**: ⭐⭐⭐ (상/중/하)

**분석 내용**:
[구체적 분석 내용 3-5문장]

**근거**:
- 평가기준 출처: [문서명 또는 기준]
- 수업지도안 근거: [해당 부분 인용]

**강점**:
1. [강점 1]
2. [강점 2]

**개선점**:
1. [개선점 1]
2. [개선점 2]

---

### 2️⃣ 내용 체계 및 성취기준 달성
[동일 형식]

### 3️⃣ 교수·학습 방법의 적절성
[동일 형식]

### 4️⃣ 평가 방향과의 일치
[동일 형식]

### 5️⃣ 개선 및 보완을 위한 제안
[동일 형식]

---

## 💡 종합 평가

### 🎯 전체 평가 요약
[5-7문장으로 전체 평가 종합]

### ✨ 주요 강점
1. [강점 1]
2. [강점 2]
3. [강점 3]

### 🔧 주요 개선 과제
1. [개선 과제 1]
2. [개선 과제 2]
3. [개선 과제 3]

### 📝 우선 실행 체크리스트

다음 항목을 우선적으로 수정·보완하시기 바랍니다:

- [ ] [실행 가능한 개선 항목 1]
- [ ] [실행 가능한 개선 항목 2]
- [ ] [실행 가능한 개선 항목 3]
- [ ] [실행 가능한 개선 항목 4]
- [ ] [실행 가능한 개선 항목 5]

---

## 📚 참고한 평가 기준

### Vector Search 참고 자료
[Vector Search로 추출된 평가기준 컨텍스트 요약]

### File Search 참고 문서
- [평가기준 문서 1 제목]
- [평가기준 문서 2 제목]
- [수업지도안 문서 제목]

---

**작성 태도**:
- 건설적이고 구체적인 피드백 제공
- 전문적이면서도 이해하기 쉬운 언어 사용
- 근거 중심의 객관적 평가
- 실행 가능한 개선 제안
```

**완료 조건**:
- ✅ prompt.md에 lesson_analysis 섹션 추가
- ✅ Markdown 형식 템플릿 포함
- ✅ 5개 평가 항목 명시

**예상 시간**: 1시간

---

#### Sub-Task 3.2: Pydantic 스키마 작성

**파일**: `app/schemas/lessonplan_analysis.py` (신규)
**담당**: backend-dev
**우선순위**: 🟢 보통
**병렬 가능**: ✅ 독립적

**구현 내용**:

```python
"""
수업 지도안 분석 스키마
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class LessonPlanAnalysisRequest(BaseModel):
    """분석 요청 스키마"""
    session_id: int = Field(..., description="채팅 세션 ID", gt=0)


class LessonPlanAnalysisResponse(BaseModel):
    """분석 응답 스키마"""
    success: bool = Field(..., description="성공 여부")
    report: Optional[str] = Field(None, description="Markdown 보고서")
    citations: Optional[Dict[str, Any]] = Field(None, description="Citation 정보")
    latency_ms: Optional[int] = Field(None, description="응답 시간 (ms)")
    error: Optional[str] = Field(None, description="에러 메시지")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "report": "# 📚 수업 지도안 평가 보고서\n\n...",
                "citations": {
                    "used_criteria": ["평가기준 1", "평가기준 2"],
                    "grounding_chunks": [
                        {
                            "source": "file_search",
                            "uri": "fileSearchStores/xxx/documents/yyy",
                            "title": "평가기준 문서"
                        }
                    ]
                },
                "latency_ms": 12350
            }
        }
```

**완료 조건**:
- ✅ Request/Response 스키마 정의
- ✅ Validation 규칙 포함
- ✅ 예시 데이터 포함

**예상 시간**: 30분

---

#### Sub-Task 3.3: 서비스 구현

**파일**: `app/services/lessonplan_analysis_service.py` (신규)
**담당**: backend-dev
**우선순위**: 🔴 높음
**병렬 가능**: ✅ Sub-task 3.1, 3.2와 병렬

**클래스 구조**:

refactor.md의 구현 세부사항 참조 (Line 260-531)

**핵심 메서드**:

1. `analyze_lesson_plan(session_id, user_id)`: 메인 분석 로직
2. `_get_criteria_context()`: Vector Search 컨텍스트 추출
3. `_get_store_ids(user_id)`: File Search Store ID 조회 (Phase 1 활용)
4. `_build_analysis_prompt()`: 프롬프트 구성
5. `_extract_citations()`: Citation 정보 추출

**주요 변경사항** (refactor.md 대비):

```python
# refactor.md의 _get_store_ids() 메서드
async def _get_store_ids(self, user_id: int) -> list[str]:
    store_ids = []
    try:
        # rubricstore 조회
        for store in self.file_search_service.client.file_search_stores.list():
            if "rubricstore" in store.display_name.lower():
                store_ids.append(store.name)
                break

        # 사용자 스토어 조회
        user_store_name = f"user-{user_id}-store"
        for store in self.file_search_service.client.file_search_stores.list():
            if user_store_name in store.display_name.lower():
                store_ids.append(store.name)
                break

        return store_ids
    except Exception as e:
        logger.error(f"Store ID 조회 실패: {e}")
        return []

# ===== Phase 1 활용 버전 (개선) =====
async def _get_store_ids(self, user_id: int) -> list[str]:
    """File Search Store ID 조회 (Phase 1 공통 유틸 사용)"""
    try:
        # Phase 1의 get_dual_store_ids() 사용
        store_ids = self.file_search_service.get_dual_store_ids(user_id)
        logger.info(f"✅ Store ID 조회 완료: {len(store_ids)}개")
        return store_ids
    except ValueError as e:
        logger.error(f"❌ Store ID 조회 실패: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ 예상치 못한 오류: {e}")
        return []
```

**완료 조건**:
- ✅ 모든 메서드 구현
- ✅ Phase 1의 get_dual_store_ids() 활용
- ✅ 에러 처리 및 타임아웃 (180초)
- ✅ Citation 추출

**예상 시간**: 2-3시간

---

#### Sub-Task 3.4: API 라우터 작성

**파일**: `app/routers/lessonplan_analysis.py` (신규)
**담당**: backend-dev
**우선순위**: 🟡 중간
**선행**: Sub-task 3.2, 3.3 완료

**구현 내용**:

refactor.md Line 776-837 참조

**엔드포인트**:
- **경로**: `POST /api/lessonplan/analyze`
- **인증**: 필수 (JWT 토큰)
- **파라미터**: LessonPlanAnalysisRequest
- **응답**: LessonPlanAnalysisResponse

**완료 조건**:
- ✅ 엔드포인트 작동
- ✅ 인증 확인
- ✅ 에러 처리

**예상 시간**: 1시간

---

#### Sub-Task 3.5: 메인 앱에 라우터 등록

**파일**: `app/main.py`
**담당**: backend-dev
**우선순위**: 🟢 보통
**선행**: Sub-task 3.4 완료

**변경 내용**:

```python
# 기존 import에 추가
from app.routers import lessonplan_analysis

# 기존 라우터 등록 후 추가
app.include_router(lessonplan_analysis.router)
```

**완료 조건**:
- ✅ 라우터 등록 확인
- ✅ API 문서 (Swagger) 업데이트

**예상 시간**: 15분

---

### 병렬 실행 가능 여부

**병렬 그룹 1** (동시 진행 가능):
- ✅ Sub-task 3.1: 프롬프트 추가
- ✅ Sub-task 3.2: 스키마 작성
- ✅ Sub-task 3.3: 서비스 구현

**순차 그룹 2** (Sub-task 3.3 완료 후):
- Sub-task 3.4: 라우터 작성

**순차 그룹 3** (Sub-task 3.4 완료 후):
- Sub-task 3.5: 메인 앱 등록

**Phase 간 병렬**:
- ✅ Phase 3 ⊥ Phase 2 (병렬 실행 가능)

---

### 예상 산출물

| 파일 | 변경 유형 | 주요 내용 |
|------|-----------|----------|
| `prompt/prompt.md` | 수정 | lesson_analysis 프롬프트 추가 |
| `app/schemas/lessonplan_analysis.py` | 신규 | Request/Response 스키마 |
| `app/services/lessonplan_analysis_service.py` | 신규 | LessonPlanAnalysisService 클래스 |
| `app/routers/lessonplan_analysis.py` | 신규 | POST /api/lessonplan/analyze 엔드포인트 |
| `app/main.py` | 수정 | 라우터 등록 |

---

### 검증 기준

#### 기능 검증
- ✅ POST /api/lessonplan/analyze 엔드포인트 정상 작동
- ✅ Markdown 보고서 생성 (5개 평가 항목 포함)
- ✅ Vector Search + File Search 이중 검색 동작
- ✅ Citation 정보 추출
- ✅ 타임아웃 처리 (180초)

#### 품질 검증
- ✅ 평가 보고서 형식 일관성
- ✅ 근거 중심 평가 (Citation 활용)
- ✅ 건설적 피드백 제공

#### 성능 검증
- ✅ 평균 응답 시간 30-60초
- ✅ 최대 응답 시간 180초 이내

---

## Phase 4: 테스트 구현

### 개요

**목표**: 모든 변경사항에 대한 단위 테스트 및 통합 테스트 작성
**담당 Agent**: qa
**우선순위**: 🔴 높음 (품질 보증)

### 선행 조건

- ✅ Phase 1, 2, 3 완료

### 테스트 전략

| 테스트 유형 | 범위 | 커버리지 목표 | 도구 |
|-------------|------|---------------|------|
| 단위 테스트 | 각 메서드/함수 | ≥ 80% | pytest + Mock |
| 통합 테스트 | API 엔드포인트 | ≥ 70% | pytest + AsyncClient |
| 회귀 테스트 | 기존 기능 | 100% | 기존 테스트 |

---

### Task 목록

#### Task 4.1: FileSearchService 테스트

**파일**: `tests/test_file_search_service.py` (신규 또는 수정)
**담당**: qa
**우선순위**: 🟡 중간
**병렬 가능**: ✅ 독립적

**테스트 케이스**:

```python
class TestFileSearchService:
    """FileSearchService 단위 테스트"""

    def test_get_dual_store_ids_success(self, service):
        """rubricstore + 사용자 스토어 조회 성공"""
        # Given
        user_id = 123
        mock_stores = [
            Mock(display_name="rubricstore", name="fileSearchStores/rubric123"),
            Mock(display_name="user-123-store", name="fileSearchStores/user123"),
        ]
        service.client.file_search_stores.list = Mock(return_value=mock_stores)

        # When
        result = service.get_dual_store_ids(user_id)

        # Then
        assert len(result) == 2
        assert "fileSearchStores/rubric123" in result
        assert "fileSearchStores/user123" in result

    def test_get_dual_store_ids_no_rubricstore(self, service):
        """rubricstore 없을 시 ValueError 발생"""
        # Given
        user_id = 123
        mock_stores = [
            Mock(display_name="other-store", name="fileSearchStores/other"),
        ]
        service.client.file_search_stores.list = Mock(return_value=mock_stores)

        # When & Then
        with pytest.raises(ValueError, match="rubricstore"):
            service.get_dual_store_ids(user_id)

    def test_get_dual_store_ids_create_user_store(self, service):
        """사용자 스토어 없을 시 자동 생성"""
        # Given
        user_id = 999
        mock_rubric = Mock(display_name="rubricstore", name="fileSearchStores/rubric")
        service.client.file_search_stores.list = Mock(return_value=[mock_rubric])
        service._get_or_create_store = Mock(
            return_value=Mock(name="fileSearchStores/user999")
        )

        # When
        result = service.get_dual_store_ids(user_id)

        # Then
        assert len(result) == 2
        service._get_or_create_store.assert_called_once_with("user-999-store")

    def test_get_dual_store_ids_caching(self, service):
        """60초 이내 재호출 시 캐시 사용"""
        # Given
        user_id = 123
        service.client.file_search_stores.list = Mock(
            return_value=[
                Mock(display_name="rubricstore", name="fileSearchStores/rubric"),
                Mock(display_name="user-123-store", name="fileSearchStores/user123"),
            ]
        )

        # When
        result1 = service.get_dual_store_ids(user_id)
        result2 = service.get_dual_store_ids(user_id)  # 캐시 히트

        # Then
        assert result1 == result2
        assert service.client.file_search_stores.list.call_count == 1  # 한 번만 호출

    def test_delete_store_by_display_name_force_true(self, service):
        """delete_store_by_display_name() force=True 사용 확인"""
        # Given
        store_name = "test-store"
        mock_store = Mock(name="fileSearchStores/test123")
        service.client.file_search_stores.list = Mock(return_value=[mock_store])
        service.client.file_search_stores.delete = Mock()

        # When
        service.delete_store_by_display_name(store_name)

        # Then
        service.client.file_search_stores.delete.assert_called_once_with(
            name=mock_store.name,
            config={'force': True}
        )
```

**완료 조건**:
- ✅ 모든 테스트 통과
- ✅ 커버리지 ≥ 80%

**예상 시간**: 1.5시간

---

#### Task 4.2: QnA 서비스 테스트

**파일**: `tests/test_qna_service_refactored.py` (수정)
**담당**: qa
**우선순위**: 🟡 중간
**병렬 가능**: ✅ 독립적

**테스트 케이스**:

```python
class TestQnAServiceRefactored:
    """리팩토링된 QnA 서비스 테스트"""

    @pytest.mark.asyncio
    async def test_answer_question_uses_get_dual_store_ids(self, service, mock_user):
        """answer_question()이 get_dual_store_ids() 사용 확인"""
        # Given
        service.file_search_service.get_dual_store_ids = Mock(
            return_value=["fileSearchStores/rubric", "fileSearchStores/user123"]
        )
        service.client.models.generate_content = Mock(
            return_value=Mock(text="답변입니다.", candidates=[])
        )

        # When
        result = await service.answer_question(
            "질문", "세션 ID", mock_user, "1"
        )

        # Then
        service.file_search_service.get_dual_store_ids.assert_called_once_with(
            user_id=mock_user["id"]
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_answer_question_store_error_handling(self, service, mock_user):
        """Store 조회 실패 시 에러 처리"""
        # Given
        service.file_search_service.get_dual_store_ids = Mock(
            side_effect=ValueError("rubricstore를 찾을 수 없습니다")
        )

        # When
        result = await service.answer_question(
            "질문", "세션 ID", mock_user, "1"
        )

        # Then
        assert result["success"] is False
        assert "평가기준 스토어" in result["error"]
```

**완료 조건**:
- ✅ 리팩토링된 로직 검증
- ✅ 에러 처리 확인

**예상 시간**: 1시간

---

#### Task 4.3: LessonPlanAnalysisService 단위 테스트

**파일**: `tests/test_lessonplan_analysis_service.py` (신규)
**담당**: qa
**우선순위**: 🔴 높음
**병렬 가능**: ✅ 독립적

**테스트 케이스**:

refactor.md Line 857-1073 참조

**주요 테스트**:
- `_get_criteria_context()` 성공/실패
- `_get_store_ids()` 성공/실패
- `_build_analysis_prompt()` 프롬프트 구성
- `_extract_citations()` Citation 추출
- `analyze_lesson_plan()` 전체 프로세스
- 타임아웃 처리
- Store 없을 시 에러

**완료 조건**:
- ✅ 모든 메서드 테스트
- ✅ 커버리지 ≥ 80%

**예상 시간**: 2시간

---

#### Task 4.4: LessonPlanAnalysis 통합 테스트

**파일**: `tests/test_lessonplan_analysis_integration.py` (신규)
**담당**: qa
**우선순위**: 🔴 높음
**병렬 가능**: ✅ 독립적

**테스트 케이스**:

```python
@pytest.mark.integration
class TestLessonPlanAnalysisIntegration:
    """API 엔드포인트 통합 테스트"""

    @pytest.mark.asyncio
    async def test_analyze_endpoint_success(self, client, auth_headers):
        """POST /api/lessonplan/analyze 성공"""
        # Given
        payload = {"session_id": 1}

        # When
        response = await client.post(
            "/api/lessonplan/analyze",
            json=payload,
            headers=auth_headers
        )

        # Then
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        assert "# 📚 수업 지도안 평가 보고서" in data["report"]

    @pytest.mark.asyncio
    async def test_analyze_endpoint_unauthorized(self, client):
        """인증 실패 (401)"""
        # Given
        payload = {"session_id": 1}

        # When
        response = await client.post(
            "/api/lessonplan/analyze",
            json=payload
        )

        # Then
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_analyze_endpoint_invalid_session(self, client, auth_headers):
        """잘못된 세션 ID (422)"""
        # Given
        payload = {"session_id": -1}

        # When
        response = await client.post(
            "/api/lessonplan/analyze",
            json=payload,
            headers=auth_headers
        )

        # Then
        assert response.status_code == 422
```

**완료 조건**:
- ✅ 모든 HTTP 상태 코드 테스트
- ✅ 실제 엔드포인트 검증

**예상 시간**: 1.5시간

---

### 병렬 실행 가능 여부

**병렬 그룹** (모두 병렬 실행 가능):
- ✅ Task 4.1: FileSearchService 테스트
- ✅ Task 4.2: QnA 서비스 테스트
- ✅ Task 4.3: LessonPlanAnalysisService 테스트
- ✅ Task 4.4: 통합 테스트

---

### 예상 산출물

| 파일 | 변경 유형 | 테스트 수 |
|------|-----------|----------|
| `tests/test_file_search_service.py` | 신규/수정 | 5개 |
| `tests/test_qna_service_refactored.py` | 수정 | 2개 |
| `tests/test_lessonplan_analysis_service.py` | 신규 | 10개 |
| `tests/test_lessonplan_analysis_integration.py` | 신규 | 3개 |

**총 테스트 수**: 20개

---

### 검증 기준

#### 테스트 통과율
- ✅ 모든 테스트 통과 (100%)

#### 코드 커버리지
- ✅ 단위 테스트: ≥ 80%
- ✅ 통합 테스트: ≥ 70%

#### 회귀 테스트
- ✅ 기존 테스트 모두 통과

---

## 의존성 관계 및 병렬 실행 전략

### 의존성 그래프

```
Phase 1 (공통 유틸리티)
    ├─→ Phase 2 (QnA 리팩토링)
    │       │
    │       └─→ Phase 4 (테스트)
    │
    └─→ Phase 3 (Lesson Analysis)
            │
            └─→ Phase 4 (테스트)
```

### 최적 실행 전략

```
시간축 →

[단계 1] Phase 1 실행 (2-3시간)
         ├─ Task 1.1 (30분)
         └─ Task 1.2-1.4 (1.5시간)

[단계 2] Phase 2 & Phase 3 병렬 실행 (4-6시간)
         ├─ Phase 2: Task 2.1-2.2 (1.5시간)
         └─ Phase 3: Sub-task 3.1-3.5 (4-6시간)
              ├─ 병렬: 3.1, 3.2, 3.3 (2-3시간)
              └─ 순차: 3.4 → 3.5 (1.15시간)

[단계 3] Phase 4 실행 (3-4시간)
         └─ Task 4.1, 4.2, 4.3, 4.4 병렬 (3-4시간)
```

**총 예상 시간**: 10-15시간 (병렬 실행 최적화 시)

---

## 리스크 관리

### Phase별 리스크 및 대응 전략

#### Phase 1 리스크

| 리스크 | 영향도 | 확률 | 대응 전략 |
|--------|--------|------|-----------|
| API 수정이 이미 완료됨 | 낮음 | 중간 | 코드 확인 후 필요한 작업만 수행 |
| 캐싱 구현 시 동기화 문제 | 중간 | 낮음 | 짧은 TTL(60초) 사용, 캐시 무효화 로직 추가 |

#### Phase 2 리스크

| 리스크 | 영향도 | 확률 | 대응 전략 |
|--------|--------|------|-----------|
| QnA 서비스 리팩토링 시 기존 기능 손상 | 높음 | 중간 | 리팩토링 전 현재 동작 확인, 리팩토링 후 회귀 테스트 |
| username/user_id 불일치 | 중간 | 낮음 | user_id 기반 메서드로 통일 |

#### Phase 3 리스크

| 리스크 | 영향도 | 확률 | 대응 전략 |
|--------|--------|------|-----------|
| Gemini API 타임아웃 (180초) 발생 | 중간 | 중간 | 타임아웃 에러 처리 구현, 명확한 메시지 |
| Store가 없을 경우 분석 불가 | 높음 | 낮음 | 명시적 에러 메시지, 사용자 안내 |

#### Phase 4 리스크

| 리스크 | 영향도 | 확률 | 대응 전략 |
|--------|--------|------|-----------|
| 테스트 환경에서 실제 Gemini API 호출 비용 | 중간 | 높음 | Mock 사용, 통합 테스트는 선택적 실행 |

---

## 검증 및 배포 계획

### 검증 체크리스트

#### Phase 1 검증
- [ ] get_dual_store_ids() 메서드 정상 작동
- [ ] rubricstore와 사용자 스토어 ID 정확히 반환
- [ ] 캐싱 동작 확인 (중복 API 호출 방지)
- [ ] 로깅 레벨 통일 (INFO/WARNING)
- [ ] 단위 테스트 통과

#### Phase 2 검증
- [ ] QnA 기능 정상 작동 (답변 생성)
- [ ] Store 조회 성공
- [ ] 코드 중복 제거 확인 (83줄 감소)
- [ ] 에러 처리 개선 확인
- [ ] 회귀 테스트 통과

#### Phase 3 검증
- [ ] POST /api/lessonplan/analyze 엔드포인트 작동
- [ ] Markdown 보고서 생성 (5개 평가 항목)
- [ ] Vector Search + File Search 이중 검색 동작
- [ ] Citation 정보 추출
- [ ] 타임아웃 처리 (180초)
- [ ] 통합 테스트 통과

#### Phase 4 검증
- [ ] 모든 단위 테스트 통과 (20개)
- [ ] 코드 커버리지 ≥ 80% (단위), ≥ 70% (통합)
- [ ] 회귀 테스트 통과

### 배포 전 최종 검증

1. **기능 검증**
   - [ ] 모든 API 엔드포인트 정상 작동
   - [ ] QnA 기능 정상 작동
   - [ ] Lesson Analysis 기능 정상 작동

2. **성능 검증**
   - [ ] API 호출 횟수 감소 확인 (캐싱)
   - [ ] 평균 응답 시간 확인

3. **품질 검증**
   - [ ] 모든 테스트 통과
   - [ ] 코드 커버리지 목표 달성
   - [ ] 코드 리뷰 완료

4. **문서 검증**
   - [ ] API 문서 업데이트 (Swagger)
   - [ ] 변경 이력 기록

---

## 부록

### 참고 문서

1. **review.md**: rubricstore 활용 리뷰 보고서
2. **refactor.md**: Lesson Analysis 기능 구현 계획
3. **CLAUDE.md**: QnA 시스템 아키텍처

### 주요 파일 위치

| 파일 | 경로 |
|------|------|
| FileSearchService | `app/services/file_search_service.py` |
| QnA 서비스 | `app/services/qna_service.py` |
| LessonPlanAnalysisService | `app/services/lessonplan_analysis_service.py` (신규) |
| 프롬프트 | `prompt/prompt.md` |

---

**문서 작성 완료**: 2025-11-23
**작성자**: Claude Code (Ultrathink 모드)
