# 평가기준 다중 Active 지원 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use agent-team-driven-development to execute this plan.

**Goal:** 동기화(reconcile)·업로드·교체로 들어온 평가기준이 자동으로 `status="active"`로 진입하고, 평가 시 다중 active 평가기준을 OR 결합한 metadata_filter로 검색하도록 한다.

**Architecture:** 기존 `uploaded` / `active` 상태 enum과 alias_map schema(v1)는 유지하면서, "단일 active 불변"을 강제하던 정규화/강등 로직을 제거한다. Vector Search 측은 AIP-160 OR 표현식으로 다중 stable_id 필터를 생성한다. UI는 radio→checkbox로 전환한다.

**Tech Stack:** FastAPI, SQLAlchemy (async), Gemini File Search (AIP-160 metadata_filter), Jinja2, Vanilla JS, pytest.

---

## Wave Analysis

### Specialists

| Role | Expertise | Tasks |
|------|-----------|-------|
| backend-engineer | Python, FastAPI async, SQLAlchemy, Gemini File Search API, pytest | Tasks 1, 2, 3, 5 |
| frontend-engineer | Jinja2 템플릿, Vanilla JS, Tailwind, HTML 접근성 | Task 4 |

### Waves

**Wave 1: Backend Foundation** — alias_map 정규화와 vector filter 생성 로직을 다중 active 의미로 확장한다. 라우터·UI 변경의 전제 조건.
- Task 1 (backend-engineer) — `_normalize_active_entries` legacy-only demote로 축소, reconcile synthesize 시 `status="active"` 진입
- Task 2 (backend-engineer) — `active_stable_id_filter` OR 결합 (`(stable_id="A" OR stable_id="B")`), `_get_active_stable_ids` 복수 반환

  *Parallel-safe because:* 서로 다른 파일(`criteria_reconciliation_service.py` vs `criteria_vector_service.py`). reconciliation은 `CriteriaVectorService` 클래스를 의존성으로 받지만 `active_stable_id_filter` 메서드는 호출하지 않음 — DI 시그니처에 영향 없음.

**Wave 2: 라우터 정책 + UI** — Wave 1의 의미가 결정된 뒤, 사용자 진입점(API + 화면)이 이를 노출한다.
- Task 3 (backend-engineer) — router `_set_status_by_stable_id` 강등 제거, `upload_criteria`/`replace_legacy_criteria` 즉시 active
- Task 4 (frontend-engineer) — `criteria_list.html` radio→checkbox, `criteria_list.js` 다중 활성 토글 처리, confirm 문구 갱신

  *Parallel-safe because:* Task 3 = `app/routers/admin/criteria.py`, Task 4 = `app/templates/admin/criteria_list.html` + `app/static/js/criteria_list.js`. 디렉토리 다름, import 관계 없음.
  *Depends on Wave 1:* Task 1 의 alias_map active 진입 의미, Task 2 의 filter OR 결합 의미. Wave 2 작업자는 "다중 active가 허용되며 search filter는 OR로 결합된다"는 invariant를 전제로 동작 수정.

**Wave 3: E2E 회귀** — 전체 흐름(reconcile → upload → activate → search)이 다중 active 시나리오에서 깨지지 않음을 검증.
- Task 5 (backend-engineer) — `tests/e2e/test_criteria_multi_active.py` 신규 작성

  *Depends on Wave 2:* 라우터와 UI 동작이 모두 최종 의미를 가진 뒤에만 회귀 검증 가능.

### Dependency Graph

```
Task 1 ─┐
        ├─→ Task 3 ─┐
Task 2 ─┘           ├─→ Task 5
        └─→ Task 4 ─┘
```

---

## Tasks

### Task 1: Reconciliation 다중 active 허용

**Specialist:** backend-engineer
**Depends on:** None
**Produces:** `_normalize_active_entries`가 legacy surrogate 의 active 만 demote 하고 real-active 는 통과시키도록 변경. `reconcile()`의 4b 단계에서 새 entry 가 `status="active"`, `activated_at=_now_iso()` 로 진입. 후속 라우터 작업이 "동기화/업로드 시 자동 active" 의미를 전제로 동작 가능.

**Files:**
- Modify: `app/services/criteria_reconciliation_service.py`
- Test: `tests/services/test_criteria_reconciliation_service.py` (없으면 신규)

**Step 1: 실패 테스트 작성**

`tests/services/test_criteria_reconciliation_service.py`에 다음 케이스 추가:

```python
import pytest
from app.schemas.alias_map import AliasMap, AliasMapEntry, empty_alias_map
from app.services.criteria_reconciliation_service import (
    _normalize_active_entries,
    legacy_surrogate_stable_id,
)


def test_normalize_keeps_multiple_real_actives():
    entries = {
        "sid_a": AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:00:00Z"),
        "sid_b": AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:01:00Z"),
        "sid_c": AliasMapEntry(alias=None, status="uploaded", activated_at=None),
    }
    result = _normalize_active_entries(entries)
    assert result["sid_a"].status == "active"
    assert result["sid_b"].status == "active"
    assert result["sid_c"].status == "uploaded"


def test_normalize_demotes_legacy_active_only():
    legacy_sid = legacy_surrogate_stable_id("doc-1")
    entries = {
        legacy_sid: AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:00:00Z"),
        "sid_a": AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:01:00Z"),
    }
    result = _normalize_active_entries(entries)
    assert result[legacy_sid].status == "uploaded"
    assert result[legacy_sid].activated_at is None
    assert result["sid_a"].status == "active"
```

추가로 reconcile() 신규 entry가 active 로 진입하는지 검증하는 단위 테스트가 기존 파일에 있다면(예: `test_reconcile_synthesizes_unmapped_entries`) `status="uploaded"`를 기대하는 어설션을 `status="active"` 와 `activated_at is not None` 으로 변경.

**Step 2: 테스트 실패 확인**

Run: `pytest tests/services/test_criteria_reconciliation_service.py -k "multiple_real_actives or demotes_legacy_active_only" -v`
Expected: FAIL (현재 normalize 는 active를 1개만 남김)

**Step 3: 구현**

`app/services/criteria_reconciliation_service.py:56-81` 의 `_normalize_active_entries` 를 다음으로 교체:

```python
def _normalize_active_entries(
    entries: dict[str, AliasMapEntry],
) -> dict[str, AliasMapEntry]:
    """Demote legacy surrogate active entries; allow multiple real actives."""
    normalized: dict[str, AliasMapEntry] = {}
    for sid, entry in entries.items():
        if entry.status == "active" and is_legacy_surrogate_stable_id(sid):
            normalized[sid] = entry.model_copy(update={
                "status": "uploaded",
                "activated_at": None,
            })
        else:
            normalized[sid] = entry
    return normalized
```

`reconcile()` 의 4b 단계 (현재 189-194 줄) 를 다음으로 교체:

```python
                # 4b. Synthesize entries for unmapped cloud docs (auto-active)
                for d in criteria_docs:
                    sid = stable_ids_by_document[d["document_id"]]
                    if sid not in cleaned:
                        cleaned[sid] = AliasMapEntry(
                            alias=None,
                            status="active",
                            activated_at=_now_iso(),
                        )
```

**Step 4: 테스트 통과 확인**

Run: `pytest tests/services/test_criteria_reconciliation_service.py -v`
Expected: PASS (신규 테스트 포함 전체 그린)

**Step 5: 커밋**

```bash
git add app/services/criteria_reconciliation_service.py tests/services/test_criteria_reconciliation_service.py
git commit -m "feat(criteria-meta): allow multiple active criteria in reconcile normalize"
```

---

### Task 2: Vector Service OR 결합 metadata_filter

**Specialist:** backend-engineer
**Depends on:** None
**Produces:** `CriteriaVectorService.active_stable_id_filter()` 가 active 평가기준이 N개일 때 `(stable_id="A" OR stable_id="B")` 형식의 AIP-160 표현을 반환. 0개면 `None`, 1개면 기존과 동일한 `stable_id="X"` 유지. 평가 시 다중 평가기준 동시 검색을 가능케 함.

**Files:**
- Modify: `app/services/criteria_vector_service.py`
- Test: `tests/services/test_criteria_vector_service.py` (없으면 신규)

**Step 1: 실패 테스트 작성**

`tests/services/test_criteria_vector_service.py` 에 다음 케이스 추가/생성:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_vector_service import CriteriaVectorService


@pytest.mark.asyncio
async def test_filter_zero_active_returns_none():
    alias_map = AliasMap(schema_version=1, updated_at="2026-05-17T00:00:00Z", entries={
        "sid_a": AliasMapEntry(alias=None, status="uploaded", activated_at=None),
    })
    svc = _make_service_with_alias_map(alias_map)
    assert await svc.active_stable_id_filter() is None


@pytest.mark.asyncio
async def test_filter_single_active_returns_equality():
    alias_map = AliasMap(schema_version=1, updated_at="2026-05-17T00:00:00Z", entries={
        "sid_a": AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:00:00Z"),
    })
    svc = _make_service_with_alias_map(alias_map)
    assert await svc.active_stable_id_filter() == 'stable_id="sid_a"'


@pytest.mark.asyncio
async def test_filter_multiple_active_returns_or_expression():
    alias_map = AliasMap(schema_version=1, updated_at="2026-05-17T00:00:00Z", entries={
        "sid_a": AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:00:00Z"),
        "sid_b": AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:01:00Z"),
    })
    svc = _make_service_with_alias_map(alias_map)
    result = await svc.active_stable_id_filter()
    # 순서는 activated_at desc 기준
    assert result == '(stable_id="sid_b" OR stable_id="sid_a")'


@pytest.mark.asyncio
async def test_filter_escapes_quotes_in_stable_id():
    alias_map = AliasMap(schema_version=1, updated_at="2026-05-17T00:00:00Z", entries={
        'sid_"a': AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:00:00Z"),
    })
    svc = _make_service_with_alias_map(alias_map)
    result = await svc.active_stable_id_filter()
    assert result == 'stable_id="sid_\\"a"'


def _make_service_with_alias_map(alias_map):
    # alias_map_service.fetch() 가 (doc_name, alias_map) 반환을 mock
    alias_svc = MagicMock()
    alias_svc.fetch = AsyncMock(return_value=("doc-name", alias_map))
    file_search_svc = MagicMock()
    svc = CriteriaVectorService.__new__(CriteriaVectorService)
    svc.file_search_service = file_search_svc
    svc.alias_map_service = alias_svc
    return svc
```

> `_make_service_with_alias_map` 의 속성명(`alias_map_service`)은 실제 `CriteriaVectorService.__init__` 의 필드명에 맞춰 조정. 구현 전 `app/services/criteria_vector_service.py` 의 `_get_active_stable_id` 가 alias_map_service 를 어떻게 참조하는지 확인하고 정확히 매칭.

**Step 2: 테스트 실패 확인**

Run: `pytest tests/services/test_criteria_vector_service.py -v`
Expected: FAIL (`test_filter_multiple_active_returns_or_expression` 가 단일 stable_id 만 반환되어 실패)

**Step 3: 구현**

`app/services/criteria_vector_service.py:151-204` 의 `active_stable_id_filter` / `_get_active_stable_id` 를 다음으로 교체:

```python
    async def active_stable_id_filter(
        self,
    ) -> Optional[str]:
        """현재 active 평가기준들에 대한 File Search metadata_filter 반환.

        - 0개: None (평가기준 미설정 안내 트리거)
        - 1개: stable_id="X"
        - N개: (stable_id="A" OR stable_id="B" ...) — AIP-160 OR 결합
        """
        active_stable_ids = await CriteriaVectorService._get_active_stable_ids(
            self.alias_map_service
        )
        if not active_stable_ids:
            return None

        def _eq(sid: str) -> str:
            escaped = sid.replace("\\", "\\\\").replace('"', '\\"')
            return f'stable_id="{escaped}"'

        if len(active_stable_ids) == 1:
            return _eq(active_stable_ids[0])

        joined = " OR ".join(_eq(sid) for sid in active_stable_ids)
        return f"({joined})"

    @staticmethod
    async def _get_active_stable_ids(
        alias_map_service,
    ) -> list[str]:
        """alias_map 에서 active stable_id 들을 activated_at desc, sid asc 순으로 반환."""
        from app.services.criteria_reconciliation_service import (
            is_legacy_surrogate_stable_id,
        )

        fetched = await alias_map_service.fetch()
        if not fetched:
            return []
        _doc_name, alias_map = fetched

        active_entries = [
            (stable_id, entry)
            for stable_id, entry in alias_map.entries.items()
            if entry.status == "active"
            and not is_legacy_surrogate_stable_id(stable_id)
        ]
        if not active_entries:
            return []

        active_entries.sort(
            key=lambda kv: (kv[1].activated_at or "", kv[0]),
            reverse=True,
        )
        return [sid for sid, _ in active_entries]
```

기존 단수 `_get_active_stable_id` 호출자가 있다면 제거되었는지 확인 (router/eval 경로는 `active_stable_id_filter` 만 호출).

**Step 4: 테스트 통과 확인**

Run: `pytest tests/services/test_criteria_vector_service.py -v`
Expected: PASS (4개 신규 테스트 모두 그린)

**Step 5: 커밋**

```bash
git add app/services/criteria_vector_service.py tests/services/test_criteria_vector_service.py
git commit -m "feat(criteria-meta): build OR metadata_filter for multi-active criteria"
```

---

### Task 3: Router 즉시 active + 강등 제거

**Specialist:** backend-engineer
**Depends on:** Task 1 (alias_map normalize 가 다중 active 허용), Task 2 (vector filter 가 OR 결합 지원)
**Produces:** POST `/admin/criteria` (upload), POST `/admin/criteria/{stable_id}/replace`, POST `/admin/criteria/{stable_id}/activate` 모두 다중 active 의미로 동작. 신규 entry/DB row 는 `status="active"`, `activated_at=now`. activate 시 기존 active 강등 안 함. legacy surrogate 의 active 진입은 여전히 400 차단.

**Files:**
- Modify: `app/routers/admin/criteria.py`
- Test: `tests/test_admin_criteria_upload_v2.py`, `tests/test_admin_criteria_activate.py`, `tests/test_admin_criteria_replace.py`

**Step 1: 실패 테스트 작성**

기존 `test_admin_criteria_activate.py` 에 다음 추가:

```python
async def test_activate_does_not_demote_existing_active(client, db_session, ...):
    """기존 active sid_a 가 있는 상태에서 sid_b 를 activate 하면 둘 다 active."""
    # given: alias_map 에 sid_a active, sid_b uploaded
    # when: POST /admin/criteria/sid_b/activate
    # then: response.status_code == 200
    #       sid_a, sid_b 둘 다 status="active" in DB and alias_map
```

기존 `test_admin_criteria_upload_v2.py` 에:

```python
async def test_upload_creates_active_entry(client, ...):
    """신규 업로드 직후 status='active', activated_at is not None."""
```

기존 `test_admin_criteria_replace.py` 에:

```python
async def test_replace_creates_active_without_demoting_others(client, ...):
    """legacy replace 시 신규 entry 는 active, 기존 다른 active 는 그대로."""
```

> 정확한 fixture 시그니처와 helper 는 기존 테스트 파일을 참고하여 동일 패턴 사용.

**Step 2: 테스트 실패 확인**

Run: `pytest tests/test_admin_criteria_activate.py tests/test_admin_criteria_upload_v2.py tests/test_admin_criteria_replace.py -v`
Expected: FAIL (신규 테스트 3개)

**Step 3: 구현**

`app/routers/admin/criteria.py` 다음 4곳 수정:

1. `_set_status_by_stable_id` (대략 610-683 줄). `target_status == "active" and entry.status == "active"` 분기에서 기존 active 강등 로직(`status="uploaded"`로 만드는 부분)을 **제거**. legacy surrogate 차단(617-619 줄)은 유지.

2. `upload_criteria` (대략 139-280 줄). alias_map entry 생성과 DB insert 시 `status="uploaded"` / `activated_at=None` → `status="active"` / `activated_at=_now_iso()` 로 변경. (228 줄, 249 줄 부근)

3. `replace_legacy_criteria` (대략 376-475 줄). 신규 alias_map entry 와 DB row 둘 다 `status="active"` / `activated_at=_now_iso()`. 기존 active 강등 코드는 처음부터 없으므로 추가 변경 없음.

4. activate 엔드포인트 description (583-585 줄): `"해당 stable_id를 active로 전환하고 기존 active는 uploaded로 강등합니다."` → `"해당 stable_id를 active로 전환합니다. 다중 active를 허용합니다."`

`_now_iso` 가 라우터에 import 되어 있지 않다면 `from app.services.criteria_reconciliation_service import _now_iso` 추가 또는 동일 헬퍼 inline.

**Step 4: 테스트 통과 확인**

Run: `pytest tests/test_admin_criteria_activate.py tests/test_admin_criteria_upload_v2.py tests/test_admin_criteria_replace.py tests/test_admin_criteria_delete_v2.py tests/test_admin_criteria_alias_patch.py -v`
Expected: PASS (회귀 없음)

**Step 5: 커밋**

```bash
git add app/routers/admin/criteria.py tests/test_admin_criteria_activate.py tests/test_admin_criteria_upload_v2.py tests/test_admin_criteria_replace.py
git commit -m "feat(criteria-meta): admin endpoints enter active immediately, no demotion"
```

---

### Task 4: UI radio → checkbox + JS 다중 활성 처리

**Specialist:** frontend-engineer
**Depends on:** None (Task 3 와는 다른 파일이라 병렬 가능. 단, 의미적으로 다중 active 가 backend 에서 허용되었음을 전제로 함 — 이 PR 안에서 함께 머지)
**Produces:** `/admin/criteria` 목록 화면이 radio 가 아닌 checkbox 로 활성/비활성 토글. 각 row 가 독립적으로 토글 가능하며, 토글 시 단 하나의 sid 만 영향 받음. confirm 문구에서 "기존 활성이 강등됩니다" 안내 제거.

**Files:**
- Modify: `app/templates/admin/criteria_list.html`
- Modify: `app/static/js/criteria_list.js`
- Test: 기존 `tests/e2e/test_admin_criteria_sync_badge_smoke.py` 에 영향 없는지 확인. UI 회귀는 Task 5 e2e 에서 커버.

**Step 1: 변경 전 동작 캡처**

별도 자동 테스트는 추가하지 않음(렌더링 변경은 Task 5 e2e 에서 검증). 변경 전 기준으로 다음을 메모:
- 현재: `<input type="radio" name="active_criteria">` 하나만 선택 가능, JS가 `previousStableId` 추적.
- 현재: 토글 시 confirm 문구 없음(즉시 fetch), 강등은 backend 가 처리.

**Step 2: 템플릿 변경**

`app/templates/admin/criteria_list.html:86-100` 를 다음으로 교체:

```html
            <div class="inline-flex items-center gap-3">
              <label class="inline-flex items-center gap-2">
                <input type="checkbox" name="active_criteria"
                       value="{{ item.stable_id }}"
                       {% if item.status == 'active' %}checked{% endif %}
                       {% if item.is_legacy %}disabled{% endif %}
                       class="active-checkbox">
                <span class="status-label">{{ '활성' if item.status == 'active' else '비활성' }}</span>
              </label>
            </div>
```

(별도 "비활성화" 버튼 제거 — checkbox 자체가 토글 역할)

**Step 3: JS 변경**

`app/static/js/criteria_list.js` 의 active 토글 부분을 교체. 구조:

```javascript
document.querySelectorAll('.active-checkbox').forEach((cb) => {
  cb.addEventListener('change', async (e) => {
    const sid = cb.value;
    const wasChecked = cb.checked;
    const previous = !wasChecked;
    try {
      const url = wasChecked
        ? `/api/admin/criteria/${sid}/activate`
        : `/api/admin/criteria/${sid}/deactivate`;
      const r = await fetch(url, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const row = cb.closest('tr');
      const label = row.querySelector('.status-label');
      if (label) label.textContent = wasChecked ? '활성' : '비활성';
    } catch (err) {
      cb.checked = previous;
      alert(`상태 변경 실패: ${err.message}`);
    }
  });
});
```

기존 `previousStableId` 추적, `confirmedActiveStableId`, `[data-action="deactivate"]` 버튼 핸들러는 모두 **제거**.

**Step 4: 브라우저 수동 점검**

`make dev` (또는 프로젝트의 dev 서버 명령) 실행 후 `/admin/criteria`:
- 2개 이상 평가기준 모두 checkbox 체크 가능
- 한 row 해제해도 다른 row 영향 없음
- legacy row 는 disabled 유지
- sync badge 영역 변경 없음

**Step 5: 커밋**

```bash
git add app/templates/admin/criteria_list.html app/static/js/criteria_list.js
git commit -m "feat(criteria-meta): UI supports independent multi-active toggles"
```

---

### Task 5: E2E 회귀 — 다중 active sync → upload → search

**Specialist:** backend-engineer
**Depends on:** Task 1, Task 2, Task 3 (라우터·서비스 변경 완료 후), Task 4 (UI는 e2e 가 templates 를 렌더링하므로 사실상 영향)
**Produces:** `tests/e2e/test_criteria_multi_active.py` 신규 — reconcile 후 모든 cloud 평가기준 active 확인, 두 번째 업로드도 active, multi-active 상태에서 filter 가 OR 형식, legacy surrogate demote 동작 회귀.

**Files:**
- Create: `tests/e2e/test_criteria_multi_active.py`

**Step 1: e2e 시나리오 작성**

`tests/e2e/test_criteria_multi_active.py`:

```python
"""E2E: 다중 active 평가기준 라이프사이클 회귀.

Mocks Gemini File Search client; exercises real DB + alias_map + router stack.
"""
import pytest

from app.repositories.app_state_repository import (
    KEY_API_KEY_HASH,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_STATE,
)


@pytest.mark.asyncio
async def test_reconcile_promotes_all_cloud_criteria_to_active(
    e2e_client, fake_vector_client, db_session
):
    """key 변경 → reconcile → cloud 3건 모두 status=active."""
    # given: cloud 에 3개 criteria document, alias_map 비어있음
    # ... fixture로 fake_vector_client.list_criteria_documents 가 3건 반환하도록
    # when: GET /admin/criteria (reconcile 트리거)
    # then: 3개 모두 status="active", activated_at not None
    raise NotImplementedError("scaffold")


@pytest.mark.asyncio
async def test_upload_after_reconcile_keeps_existing_actives(
    e2e_client, fake_vector_client, db_session
):
    """기존 2 active + 신규 upload → 3 active."""
    raise NotImplementedError("scaffold")


@pytest.mark.asyncio
async def test_search_filter_uses_or_expression_for_multi_active(
    e2e_client, fake_vector_client, db_session
):
    """multi-active 상태에서 search → metadata_filter == '(stable_id="X" OR stable_id="Y")'."""
    raise NotImplementedError("scaffold")


@pytest.mark.asyncio
async def test_reconcile_demotes_only_legacy_surrogate_actives(
    e2e_client, fake_vector_client, db_session
):
    """alias_map 에 legacy active + real active 가 섞여 있어도 real 은 유지, legacy 만 demote."""
    raise NotImplementedError("scaffold")
```

> `scaffold` 부분은 기존 `tests/e2e/test_admin_criteria_sync_badge_smoke.py` 의 fixture 와 헬퍼를 동일 패턴으로 사용. fake_vector_client 의 동작은 reconcile 단위 테스트에서 사용 중인 pattern을 재사용.

**Step 2: 테스트 실패 확인**

Run: `pytest tests/e2e/test_criteria_multi_active.py -v`
Expected: FAIL — 4개 모두 `NotImplementedError`

**Step 3: scaffold → 실 구현**

`raise NotImplementedError("scaffold")` 를 실제 assertion 으로 채움. fixture가 부족하다면 `tests/conftest.py` 또는 `tests/e2e/conftest.py` 에 helper 추가 가능.

**Step 4: 테스트 통과 확인**

Run: `pytest tests/e2e/test_criteria_multi_active.py -v`
Expected: PASS (4개 그린)

추가 회귀: `pytest tests/ -k "criteria" -v` 전체 그린 확인.

**Step 5: 커밋**

```bash
git add tests/e2e/test_criteria_multi_active.py tests/e2e/conftest.py
git commit -m "test(criteria-meta): e2e regression for multi-active lifecycle"
```

---

## Execution

Plan complete and saved to `docs/plans/2026-05-17-criteria-multi-active.md`.

**Recommended: Agent Team-Driven** — Parallel specialist agents, wave-based execution, two-stage review after each task.

**Alternative: Subagent-Driven** — Serial execution, simpler orchestration, no team overhead. Better if <3 tasks or tasks are tightly coupled.

Which approach?
