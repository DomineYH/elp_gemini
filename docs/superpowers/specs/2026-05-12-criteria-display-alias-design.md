# 평가기준 표시명(Display Alias) 통일 — 설계 문서

- **작성일:** 2026-05-12
- **작성자:** Claude (브레인스토밍 세션 기반)
- **상태:** Draft — 사용자 검토 대기

## 1. 배경

현재 평가기준(`criteria`) 이름은 화면별로 다른 값이 표시되어 일관성이 없다.

| # | 화면 | 현재 표시 값 | 출처 |
|---|---|---|---|
| 1 | 관리자 평가기준 목록 — 상단 표 (`templates/admin/criteria_list.html`) | DB 원본 `title` | `Criteria.title` |
| 2 | 관리자 평가기준 목록 — 하단 클라우드 표 | 클라우드 `display_name` (ASCII 변환) | `CriteriaVectorService.list_criteria_documents()` |
| 3 | 관리자 평가기준 상세 (`templates/admin/criteria_detail.html`) | DB 원본 `title` | `Criteria.title` |
| 4 | 사용자 대시보드 "활성 평가 기준" 박스 (`templates/user/dashboard.html:304`) | 클라우드 `display_name` (ASCII 변환) | `CriteriaVectorService.list_criteria_documents()` |
| 5 | QnA 답변 출처 "📋 평가기준" (`templates/user/viewer.html:251~262`) | DB 원본 `title` (citation→DB lookup) | `Criteria.title` |

또한 클라우드(Gemini File Search) 측 `display_name`은 `_sanitize_display_name()`에 의해 ASCII로 변환되어 한글 평가기준의 가독성이 매우 떨어진다(예: `초등6학년_수업.pdf` → `_pdf`).

## 2. 목표

1. 시스템 전체에서 평가기준 표시명이 **하나의 값**으로 통일된다.
2. 관리자가 평가기준의 표시명을 **편집할 수 있다**.
3. 클라우드 측 저장(`Gemini display_name`)은 **변경하지 않는다** (재업로드 비용 회피, API 제약 회피).
4. 관리자 클라우드 문서 표에 **DB 평가기준 제목 컬럼**을 추가하여 어떤 DB 행이 어떤 클라우드 문서와 매칭되는지 식별 가능하다.

## 3. 비목표 (Out of scope)

- 클라우드 `display_name` 자체의 실제 수정/재업로드
- 표시명 중복 검사
- 표시명 변경 이력/감사 로그
- 엔드유저에게 표시명 편집 권한 부여 (관리자 전용 유지)

## 4. 결정 사항 (브레인스토밍 합의 내용)

| 항목 | 결정 |
|---|---|
| 저장 정책 | DB의 `title`(원본 파일명)과 클라우드의 `display_name`(ASCII)는 현행 유지 |
| 표시 정책 | 모든 5개 화면에서 `display_alias`(신규 컬럼) 사용 |
| Fallback | `display_alias`가 NULL/빈 값이면 `Criteria.title`로 대체 |
| 편집 가능 범위 | 관리자만 — ASCII 문자만 허용 |
| 클라우드 호출 | alias 변경 시 클라우드 재업로드 없음 (DB-only) |
| 적용 화면 | 위 표의 5개 화면 모두 |
| 클라우드 문서 표 컬럼 구성 | `평가기준 title (DB)` \| `표시 이름 alias (편집)` \| `문서 ID` |

## 5. 데이터 모델

### 5.1 `criteria` 테이블 변경

```sql
ALTER TABLE criteria
  ADD COLUMN display_alias VARCHAR(255) NULL
  COMMENT '관리자가 편집 가능한 ASCII-only 표시명. NULL이면 title을 fallback';
```

### 5.2 `app/models/criteria.py` 변경

```python
display_alias = Column(
    String(255),
    nullable=True,
    comment="관리자 편집용 ASCII 표시명 (NULL이면 title을 fallback)"
)
```

### 5.3 마이그레이션 정책

- 신규 컬럼은 `NULL` 허용. 기존 행은 모두 `display_alias = NULL`로 시작.
- `_sanitize_display_name`을 적용한 자동 백필은 **하지 않음** (관리자가 의도적으로 설정할 때까지 fallback 동작 유지).
- 롤백: `ALTER TABLE criteria DROP COLUMN display_alias;` 만 수행하면 됨. 다른 코드 의존성은 fallback 처리로 안전.

## 6. 컴포넌트별 변경

### 6.1 스키마 (`app/schemas/criteria.py`)

신규:
```python
class UpdateDisplayAliasRequest(BaseModel):
    display_alias: str | None

    @validator('display_alias')
    def validate(cls, v):
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if not v.isascii():
            raise ValueError("ASCII 문자만 허용됩니다.")
        if len(v) > 255:
            raise ValueError("255자 이내로 입력하세요.")
        return v
```

### 6.2 리포지토리 (`app/repositories/criteria_repository.py`)

추가 메서드:
- `update_display_alias(criteria_id: int, alias: str | None) -> Criteria | None`
- `get_criteria_map_by_document_ids(doc_ids: list[str]) -> dict[str, Criteria]`
  - 하단 클라우드 표 렌더링 시 `cloud.document_id → DB Criteria` 매핑용

### 6.3 라우터 — Admin API (`app/routers/admin/criteria.py`)

신규 엔드포인트:
```
PATCH /api/admin/criteria/{criteria_id}/display-alias
Auth: 관리자
Body: { "display_alias": str | null }
Response:
  200 OK   { "success": true, "criteria_id": int, "display_alias": str | null }
  404      { "detail": "평가기준을 찾을 수 없습니다." }
  422      { "detail": "ASCII 문자만 허용됩니다." (등) }
```

DB만 업데이트. 클라우드 호출 없음.

### 6.4 라우터 — Admin View (`app/routers/admin/criteria_views.py`)

`criteria_list()`에서:
- 클라우드 문서 목록(`cloud_documents`)에 매칭되는 DB Criteria를 lookup
- 템플릿에 `cloud_documents = [{document_id, alias, title}]` 형태로 enrich
- 상단 표용 `criteria_items.documents[].display_alias`도 함께 전달

### 6.5 라우터 — 사용자 뷰 (`app/routers/views.py`)

`user_dashboard()`와 `upload_document()` 두 곳에서:
- 현재 `CriteriaVectorService.list_criteria_documents()` 호출(클라우드 직접 조회) 제거
- 대신 `CriteriaRepository.get_active_criteria()`로 DB 조회
- 템플릿에 `criteria_documents = [{name: alias or title, ...}]` 형태로 전달

부작용: 사용자 대시보드 로딩이 클라우드 호출 1회만큼 빨라짐.

### 6.6 서비스 (`app/services/criteria_context_service.py`)

`criteria_metadata` 구성 시:
```python
criteria_metadata.append({
    "id": criteria.id,
    "title": criteria.display_alias or criteria.title,  # 변경
    "file_path": criteria.file_path,
})
```
QnA 응답의 citation 표시값에 alias가 반영됨. 내부 lookup 키(`Criteria.title.like(...)`)는 그대로 유지(클라우드에서 돌아온 sanitized title과 매칭해야 하므로).

### 6.7 템플릿 변경

**`templates/admin/criteria_list.html` — 상단 표 "제목" 셀:**
```html
<div class="text-sm font-medium text-gray-900">{{ item.title }}</div>
{% if item.display_alias %}
  <div class="text-xs text-blue-600 mt-1">표시명: {{ item.display_alias }}</div>
{% endif %}
<div class="text-xs text-gray-500 mt-1">ID: {{ item.id }}</div>
```

**`templates/admin/criteria_list.html` — 하단 클라우드 표:**
```html
<thead>
  <tr>
    <th>평가기준 제목</th>
    <th>표시 이름</th>
    <th>문서 ID</th>
  </tr>
</thead>
<tbody>
  {% for doc in cloud_documents %}
  <tr>
    <td>{{ doc.title or '(매칭 없음)' }}</td>
    <td>
      <span class="alias-cell"
            data-criteria-id="{{ doc.criteria_id }}"
            data-original="{{ doc.alias or '' }}">
        {{ doc.alias or '(미설정)' }}
      </span>
    </td>
    <td class="font-mono text-xs">{{ doc.document_id }}</td>
  </tr>
  {% endfor %}
</tbody>
```
- alias 셀: 클릭 시 `<input>`으로 전환. Enter 또는 blur 시 `PATCH` 호출 → 갱신.
- 매칭 없는 행(고아 클라우드 문서)은 alias 편집 불가(`criteria_id`가 없음).

**`templates/admin/criteria_detail.html`:**
- 상단 제목 영역 아래에 "표시명" 표시 + 편집 버튼(또는 인라인 입력)

**`templates/user/dashboard.html` (line ~304):**
```html
{{ criteria.name }}   <!-- 라우터에서 alias or title을 'name'으로 변환해서 전달 -->
```

### 6.8 정적 JS (`app/static/js/criteria_list.js`)

신규 함수:
```js
async function updateDisplayAlias(criteriaId, newAlias) {
  // 1) ASCII 사전 검증
  if (newAlias && !/^[\x00-\x7F]*$/.test(newAlias)) {
    showToast("ASCII 문자만 허용됩니다.", "error");
    return false;
  }
  // 2) PATCH 호출
  const res = await fetch(`/api/admin/criteria/${criteriaId}/display-alias`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_alias: newAlias || null }),
  });
  // 3) 성공/실패 처리
}

// 인라인 편집 이벤트 바인딩
document.querySelectorAll('.alias-cell').forEach(cell => {
  cell.addEventListener('click', () => activateAliasEdit(cell));
});
```

## 7. 테스트 계획

### 7.1 단위 테스트
- `tests/test_criteria_repository.py`: `update_display_alias` 정상/존재하지 않는 ID/NULL 설정
- `tests/test_criteria_schema.py`: `UpdateDisplayAliasRequest` — ASCII 통과, 한글/이모지 거부, 길이 초과 거부, NULL/빈 문자열 → None

### 7.2 라우터 테스트
- `PATCH /api/admin/criteria/{id}/display-alias`:
  - 관리자: 200
  - 비관리자: 401/403
  - 존재하지 않는 ID: 404
  - 비ASCII 입력: 422

### 7.3 뷰/통합 테스트
- 관리자 목록 페이지: 상단 표에 `display_alias` 표시, 하단 클라우드 표에 매칭된 DB title 표시
- 사용자 대시보드: `display_alias`가 설정된 활성 평가기준은 alias가, NULL이면 title이 표시됨
- QnA citation 메타데이터: alias가 있으면 alias, 없으면 title이 반환됨

### 7.4 회귀 확인
- 평가기준 업로드 → 활성화 → 클라우드 동기화: alias 변경과 무관하게 정상 동작
- alias 변경 시 클라우드 측 호출이 발생하지 않음 (네트워크 mock 검증)

## 8. 영향 받는 파일 (체크리스트)

- [ ] `app/models/criteria.py` — 컬럼 추가
- [ ] `app/migrations/` — 마이그레이션 스크립트 추가 (기존 패턴 따름)
- [ ] `app/schemas/criteria.py` — `UpdateDisplayAliasRequest` 추가
- [ ] `app/repositories/criteria_repository.py` — 메서드 2개 추가
- [ ] `app/routers/admin/criteria.py` — `PATCH` 엔드포인트 추가
- [ ] `app/routers/admin/criteria_views.py` — 데이터 enrichment
- [ ] `app/routers/views.py` — 사용자 대시보드 데이터 소스 전환
- [ ] `app/services/criteria_context_service.py` — citation title에 alias fallback 반영
- [ ] `app/templates/admin/criteria_list.html` — 상·하단 표 변경
- [ ] `app/templates/admin/criteria_detail.html` — alias 편집 UI 추가
- [ ] `app/templates/user/dashboard.html` — alias 표시 변경
- [ ] `app/static/js/criteria_list.js` — 인라인 편집 JS 추가
- [ ] `tests/test_criteria_repository.py` — 신규 또는 보강
- [ ] `tests/test_criteria_schema.py` — 신규 또는 보강
- [ ] `tests/test_admin_criteria_router.py` — 신규 또는 보강
- [ ] `tests/test_user_dashboard.py` — 신규 또는 보강

## 9. 롤아웃 순서

1. 마이그레이션 + 모델 변경 → DB 컬럼 추가 (배포 후 영향 없음, NULL fallback)
2. 리포지토리/스키마 추가 → 백엔드 API 추가
3. 라우터 + 뷰 데이터 보강 → 사용자 대시보드와 QnA citation도 alias fallback 동작
4. 템플릿 변경 → 화면에 노출
5. 정적 JS 변경 → 인라인 편집 활성화
6. 테스트 추가/실행

각 단계 사이에 점진 배포 가능 — 모든 단계가 fallback으로 안전.

## 10. 위험과 완화

| 위험 | 완화 |
|---|---|
| 클라우드 문서와 DB 행이 매칭되지 않는 고아 행 존재 | 하단 표에서 "(매칭 없음)"으로 표기, alias 편집 비활성화 |
| 관리자가 비ASCII를 강제로 보내려 시도 | Pydantic 서버측 검증 + 클라이언트 정규식 사전 검증 |
| alias가 너무 길어 UI가 깨짐 | 255자 제한 + 템플릿에서 `truncate` 또는 CSS `overflow` |
| 사용자 대시보드 표시 방식 변경으로 인한 UX 회귀 | 변경 전 스냅샷 비교, alias NULL 케이스에서 기존 동작과 시각적으로 동일하도록 fallback |
