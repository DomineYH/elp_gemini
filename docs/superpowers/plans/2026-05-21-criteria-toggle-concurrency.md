# Criteria Toggle Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 평가기준 활성/비활성 체크박스 연속 토글 시 발생하는 503/needs_resync를 제거하고, 반영 중에는 UI에 "반영중" 라벨로 입력 잠금을 표시한다.

**Architecture:** 클라이언트(체크박스 in-flight 잠금 + "반영중" 라벨)와 서버(모듈 전역 `asyncio.Lock`으로 모든 alias_map mutation 경로를 직렬화) 양쪽 모두에 보호를 도입한다. 기존 optimistic update와 recovery 흐름(PR #75, #77)은 보존한다.

**Tech Stack:** FastAPI, asyncio, vanilla JS (CSP-friendly), pytest + pytest-asyncio, unittest.mock

**Spec:** `docs/superpowers/specs/2026-05-21-criteria-toggle-concurrency-design.md`

**Issue:** https://github.com/DomineYH/elp_gemini/issues/78

---

## File Structure

수정/추가 파일과 책임:

- `app/static/js/criteria_list.js` (modify) — 체크박스 핸들러에 in-flight 잠금 + "반영중" 라벨 표시
- `app/routers/admin/criteria.py` (modify) — 모듈 전역 `_alias_map_mutation_lock` 도입 + alias_map mutation 본문 6개를 `async with`로 감싸기
- `tests/test_criteria_list_js.py` (modify) — "반영중" 라벨 + `cb.disabled` 토글 정적 검증 추가
- `tests/test_criteria_toggle_serialization.py` (create) — `asyncio.gather`로 동시 mutation이 직렬화됨을 검증

각 파일은 단일 책임을 유지한다. 기존 패턴(string-match JS test, AsyncMock 기반 router 테스트)을 따른다.

---

## Task 1: 클라이언트 in-flight 잠금 + "반영중" 라벨

**Files:**
- Modify: `app/static/js/criteria_list.js:5-26`
- Test: `tests/test_criteria_list_js.py`

체크박스 토글 동안 추가 클릭을 막고 라벨로 "반영중" 상태를 표시한다. 기존 optimistic update(라벨이 fetch 전에 변경됨)는 유지하되, 시작 시 `wasChecked ? '활성 반영중…' : '비활성 반영중…'`으로 표시하고 성공 시 `wasChecked ? '활성' : '비활성'`으로 확정한다.

- [ ] **Step 1: Write the failing tests**

`tests/test_criteria_list_js.py` 끝에 다음 테스트를 추가:

```python
def test_checkbox_disabled_while_request_in_flight():
    """change 핸들러는 fetch 호출 전에 체크박스를 disable 해야 한다.

    근거: alias_map.replace() 가 수 초~수십 초 걸리는 동안 사용자가 다시
    토글하면 두 번째 요청이 서버 측 alias_map 충돌을 일으켜 503/needs_resync
    가 발생한다. 클라이언트에서 in-flight 잠금으로 첫 단계 차단.
    """
    src = JS_SOURCE.read_text()

    fetch_index = src.find('await fetch(url')
    assert fetch_index != -1
    disable_index = src.find('cb.disabled = true')
    assert disable_index != -1, "체크박스 disable 라인이 존재해야 한다"
    assert disable_index < fetch_index, (
        "cb.disabled = true 는 fetch 호출보다 먼저 실행되어야 한다"
    )


def test_label_shows_pending_while_request_in_flight():
    """change 시작 시 라벨은 '반영중…' 으로 표시되어야 한다.

    근거: optimistic 라벨 갱신은 유지하되, 아직 클라우드에 commit 되지
    않았음을 사용자에게 알린다.
    """
    src = JS_SOURCE.read_text()

    pending_active = "'활성 반영중…'"
    pending_inactive = "'비활성 반영중…'"
    assert pending_active in src, "'활성 반영중…' 라벨이 존재해야 한다"
    assert pending_inactive in src, "'비활성 반영중…' 라벨이 존재해야 한다"


def test_checkbox_re_enabled_after_request_finishes():
    """요청 종료 후 체크박스는 항상 다시 enable 되어야 한다 (try/finally).

    근거: 성공/실패 어느 경로에서도 disabled 상태가 남으면 행이 영구
    잠긴다.
    """
    src = JS_SOURCE.read_text()

    # finally 블록 또는 catch/then 양쪽에서 enable 보장
    assert 'cb.disabled = false' in src, (
        "응답 후 체크박스를 enable 하는 라인이 존재해야 한다"
    )
    # finally 키워드 사용 (가장 안전한 패턴)
    assert '} finally {' in src, (
        "try/finally 패턴으로 disabled 해제를 보장해야 한다"
    )
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:

```bash
.venv/bin/pytest tests/test_criteria_list_js.py::test_checkbox_disabled_while_request_in_flight tests/test_criteria_list_js.py::test_label_shows_pending_while_request_in_flight tests/test_criteria_list_js.py::test_checkbox_re_enabled_after_request_finishes -v
```

Expected: 3 FAIL (라벨/disabled 라인 미존재).

- [ ] **Step 3: Implement criteria_list.js changes**

`app/static/js/criteria_list.js`의 `.active-checkbox` change 핸들러(파일 line 5-26)를 다음으로 교체:

```javascript
  document.querySelectorAll('.active-checkbox').forEach((cb) => {
    cb.addEventListener('change', async () => {
      const sid = cb.value;
      const wasChecked = cb.checked;
      const previous = !wasChecked;
      const row = cb.closest('tr');
      const label = row.querySelector('.status-label');
      const previousLabelText = label ? label.textContent : null;
      const finalLabelText = wasChecked ? '활성' : '비활성';
      const pendingLabelText = wasChecked ? '활성 반영중…' : '비활성 반영중…';
      if (label) label.textContent = pendingLabelText;
      cb.disabled = true;
      try {
        const url = wasChecked
          ? `/api/admin/criteria/${sid}/activate`
          : `/api/admin/criteria/${sid}/deactivate`;
        const r = await fetch(url, { method: 'POST' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (label) label.textContent = finalLabelText;
      } catch (err) {
        cb.checked = previous;
        if (label) label.textContent = previousLabelText;
        alert(`상태 변경 실패: ${err.message}`);
      } finally {
        cb.disabled = false;
      }
    });
  });
```

핵심:
- `cb.disabled = true`는 `fetch` 호출 전에 실행됨 (테스트 1 만족).
- 라벨은 시작 시 "반영중…" → 성공 시 "활성"/"비활성" 확정 (테스트 2 만족).
- `try/finally` 블록에서 `cb.disabled = false` (테스트 3 만족).
- 기존 optimistic update와 실패 시 롤백 동작은 보존.

- [ ] **Step 4: Run the new tests and confirm they pass**

Run:

```bash
.venv/bin/pytest tests/test_criteria_list_js.py -v
```

Expected: PASS (기존 5개 + 신규 3개 = 8개 모두).

특히 `test_label_updates_optimistically_before_fetch`는 여전히 통과해야 함 — 라벨 갱신("활성 반영중…" 라인도 매치)이 fetch 호출보다 먼저 등장하므로.

> 주의: `test_label_updates_optimistically_before_fetch`는 정확히 `"label.textContent = wasChecked ? '활성' : '비활성'"` 라인을 찾는다. 위 구현에서는 이 라인이 catch가 아닌 try 블록 안에 있으며 fetch 이후에 있다. 따라서 그 테스트는 **수정이 필요**하다.

`tests/test_criteria_list_js.py`의 `test_label_updates_optimistically_before_fetch` 본문을 다음으로 교체:

```python
def test_label_updates_optimistically_before_fetch():
    """체크박스 change 시 라벨은 fetch 응답 전에 즉시 갱신되어야 한다.

    근거: 백엔드 alias_map.replace()는 클라우드 업로드 폴링(최대 60초)으로
    느릴 수 있으므로, UI 라벨은 optimistic 업데이트('반영중…') 후 응답
    수신 시 최종 텍스트로 확정한다.
    """
    src = JS_SOURCE.read_text()

    fetch_index = src.find('await fetch(url')
    assert fetch_index != -1, "fetch 호출이 존재해야 한다"

    # 시작 시 pending 라벨이 fetch 호출보다 먼저 등장해야 한다.
    pending_assignment = (
        "label.textContent = pendingLabelText"
    )
    pending_index = src.find(pending_assignment)
    assert pending_index != -1, "pending 라벨 할당 라인이 존재해야 한다"
    assert pending_index < fetch_index, (
        "pending 라벨 할당은 fetch 호출보다 먼저 실행되어야 한다 "
        "(optimistic update)"
    )
```

- [ ] **Step 5: Run the full JS test module**

Run:

```bash
.venv/bin/pytest tests/test_criteria_list_js.py -v
```

Expected: PASS (8/8).

- [ ] **Step 6: Commit**

```bash
git add app/static/js/criteria_list.js tests/test_criteria_list_js.py
git commit -m "$(cat <<'EOF'
feat(criteria-list): lock checkbox and show '반영중' label while toggle in flight

- Disable the active-checkbox immediately on change and re-enable in finally.
- Show "활성 반영중…/비활성 반영중…" while the POST is outstanding;
  switch to "활성/비활성" only on success.
- Preserve PR #75 optimistic update semantics and failure rollback.

Refs: #78
EOF
)"
```

---

## Task 2: 서버 모듈 전역 락 + 활성/비활성 토글 직렬화

**Files:**
- Modify: `app/routers/admin/criteria.py` (이전 약 line 53 이후 모듈 상수 영역, `_set_status_by_stable_id`)
- Test: `tests/test_criteria_toggle_serialization.py` (신규)

`app/routers/admin/criteria.py`에 모듈 전역 `_alias_map_mutation_lock = asyncio.Lock()`을 도입하고, `_set_status_by_stable_id` 본문 전체를 `async with _alias_map_mutation_lock:`로 감싼다. 이로써 동시 토글이 직렬화된다.

- [ ] **Step 1: Write the failing test**

`tests/test_criteria_toggle_serialization.py` 생성:

```python
"""
평가기준 활성/비활성 토글의 alias_map mutation 직렬화 회귀 테스트.

근거 (이슈 #78):
- 클라우드 alias-map 반영(upload-then-delete)이 진행 중인 동안 두 번째
  mutation 이 들어오면 alias_map 다중 문서 충돌 또는 needs_resync 마킹으로
  HTTP 503 이 발생한다.
- 해결: app.routers.admin.criteria 모듈에 _alias_map_mutation_lock 을 두고
  alias_map 변형 경로를 직렬화한다.

본 모듈은 동시 호출 시 alias_svc.replace 가 결코 동시에 두 번 진행 중이지
않음을 검증한다.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.admin.criteria import (
    activate_by_stable_id,
    deactivate_by_stable_id,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry


def _alias_map_with(stable_ids: list[str], status: str = "uploaded") -> AliasMap:
    return AliasMap(
        schema_version=1,
        updated_at="2026-05-21T00:00:00Z",
        entries={
            sid: AliasMapEntry(alias=None, status=status, activated_at=None)
            for sid in stable_ids
        },
    )


class _ConcurrencyProbe:
    """alias_svc.replace mock 으로 사용. 동시 진행 횟수를 추적한다."""

    def __init__(self, sleep_seconds: float = 0.05):
        self.in_progress = 0
        self.max_in_progress = 0
        self.calls = 0
        self._sleep = sleep_seconds

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        self.in_progress += 1
        if self.in_progress > self.max_in_progress:
            self.max_in_progress = self.in_progress
        await asyncio.sleep(self._sleep)
        self.in_progress -= 1
        return "fileSearchStores/s/documents/alias-map-new"


@pytest.mark.asyncio
async def test_concurrent_toggle_same_stable_id_is_serialized():
    """동일 stable_id 의 activate+deactivate 동시 호출이 직렬화된다."""
    stable_id = "01HTOGGLE"
    probe = _ConcurrencyProbe()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "fileSearchStores/s/documents/alias-map-old",
            _alias_map_with([stable_id]),
        ))
        alias.replace = AsyncMock(side_effect=probe)

        repo = repo_cls.return_value
        row = MagicMock()
        row.status = "uploaded"
        row.activated_at = None
        repo.get_criteria_by_stable_id = AsyncMock(return_value=row)

        db = AsyncMock()

        results = await asyncio.gather(
            activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
            deactivate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
        )

    assert len(results) == 2
    assert probe.calls == 2, "두 mutation 모두 alias_svc.replace 를 호출해야 한다"
    assert probe.max_in_progress == 1, (
        "alias_svc.replace 가 동시에 두 번 진행 중이면 안 된다 "
        "(asyncio.Lock 직렬화 실패)"
    )


@pytest.mark.asyncio
async def test_concurrent_toggle_different_stable_ids_is_serialized():
    """서로 다른 stable_id 동시 호출도 alias_map 은 단일 문서이므로 직렬화된다."""
    sid_a = "01HTOGGLEA"
    sid_b = "01HTOGGLEB"
    probe = _ConcurrencyProbe()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "fileSearchStores/s/documents/alias-map-old",
            _alias_map_with([sid_a, sid_b]),
        ))
        alias.replace = AsyncMock(side_effect=probe)

        repo = repo_cls.return_value
        row = MagicMock()
        row.status = "uploaded"
        row.activated_at = None
        repo.get_criteria_by_stable_id = AsyncMock(return_value=row)

        db = AsyncMock()

        results = await asyncio.gather(
            activate_by_stable_id(
                stable_id=sid_a,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
            activate_by_stable_id(
                stable_id=sid_b,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
        )

    assert len(results) == 2
    assert probe.calls == 2
    assert probe.max_in_progress == 1


@pytest.mark.asyncio
async def test_toggle_lock_is_released_after_exception():
    """첫 mutation 이 예외로 실패해도 락은 풀려서 후속 호출이 진행된다."""
    stable_id = "01HTOGGLE"
    probe = _ConcurrencyProbe()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls, patch(
        "app.routers.admin.criteria._recover_status_mutation_from_cloud",
        new=AsyncMock(return_value=False),
    ):
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "fileSearchStores/s/documents/alias-map-old",
            _alias_map_with([stable_id]),
        ))
        # 첫 호출은 실패, 두 번째 호출은 정상 진행
        alias.replace = AsyncMock(side_effect=[
            RuntimeError("transient cloud error"),
            probe.__call__(),
        ])

        repo = repo_cls.return_value
        row = MagicMock()
        row.status = "uploaded"
        row.activated_at = None
        repo.get_criteria_by_stable_id = AsyncMock(return_value=row)

        state = state_cls.return_value
        state.set = AsyncMock()

        db = AsyncMock()

        # 첫 호출: 500 예상
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )
        assert exc_info.value.status_code == 500

        # 두 번째 호출: 성공해야 함 (락이 풀렸어야 함)
        result = await deactivate_by_stable_id(
            stable_id=stable_id,
            current_admin=object(),
            _sync_ready=None,
            db=db,
        )
        assert result["status"] == "uploaded"
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:

```bash
.venv/bin/pytest tests/test_criteria_toggle_serialization.py -v
```

Expected: 3 FAIL.
- `test_concurrent_toggle_same_stable_id_is_serialized` 와 `test_concurrent_toggle_different_stable_ids_is_serialized` 는 `assert probe.max_in_progress == 1` 에서 실패 (현재 1이 아니라 2).
- `test_toggle_lock_is_released_after_exception` 은 두 번째 호출 시점에서 락이 없으므로 통과할 수도 있으나, 락 도입 후 정상 동작 회귀를 위한 가드 역할.

- [ ] **Step 3: Implement the module-level lock**

`app/routers/admin/criteria.py` 수정:

(a) 파일 상단 임포트에 `asyncio` 추가 (이미 다른 곳에서 쓰지 않으면). 파일에서 import 영역 확인:

```python
import asyncio
import logging
import os
import tempfile
```

(b) 모듈 상수 영역(현재 `logger = logging.getLogger(__name__)` 바로 다음, line 약 53)에 락 추가:

```python
logger = logging.getLogger(__name__)

# alias-map 문서는 File Search store 내 단일 문서이며, replace() 가
# upload-then-delete 순서로 진행되어 수 초~수십 초 동안 두 개의 문서가
# 공존한다. 동시에 다른 mutation 의 fetch() 가 그 두 문서를 모두 보면
# AliasMapParseError 가 발생해 sync_state=needs_resync 로 떨어진다 (이슈 #78).
# 모든 alias_map 변형 경로를 이 락으로 직렬화한다.
_alias_map_mutation_lock = asyncio.Lock()
```

(c) `_set_status_by_stable_id` 본문을 락으로 감싸기. 현재 함수(line 694-775):

기존:

```python
async def _set_status_by_stable_id(
    db: AsyncSession, stable_id: str, target_status: str
) -> dict:
    """
    alias_map과 DB 캐시를 동시에 업데이트.
    다중 active를 허용합니다.
    """
    if target_status == "active" and is_legacy_surrogate_stable_id(stable_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "Legacy(pre-v2) 평가기준은 직접 활성화할 수 없습니다. "
                "목록의 '교체' 버튼으로 동일하거나 대체할 PDF를 재업로드하면 "
                "v2 stable_id가 발급되어 활성화할 수 있습니다."
            ),
        )

    cloud_write_started = False
    try:
        vec = CriteriaVectorService()
        ...
        await _raise_criteria_mutation_failed(
            db,
            e,
            cloud_write_started=cloud_write_started,
        )
```

수정 후 (legacy 가드는 락 밖에, 나머지 본문은 락 안에):

```python
async def _set_status_by_stable_id(
    db: AsyncSession, stable_id: str, target_status: str
) -> dict:
    """
    alias_map과 DB 캐시를 동시에 업데이트.
    다중 active를 허용합니다.
    """
    if target_status == "active" and is_legacy_surrogate_stable_id(stable_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "Legacy(pre-v2) 평가기준은 직접 활성화할 수 없습니다. "
                "목록의 '교체' 버튼으로 동일하거나 대체할 PDF를 재업로드하면 "
                "v2 stable_id가 발급되어 활성화할 수 있습니다."
            ),
        )

    async with _alias_map_mutation_lock:
        cloud_write_started = False
        try:
            vec = CriteriaVectorService()
            alias_svc = CriteriaAliasMapService(
                client=vec.file_search_service.client,
                store_display_name=settings.FS_RUBRIC_STORE_NAME,
            )

            try:
                fetched = await alias_svc.fetch()
            except AliasMapParseError as e:
                await _raise_alias_map_parse_unavailable(db, e)
            if fetched is None:
                await _raise_alias_map_missing_conflict(db)
            old_doc_name, alias_map = fetched
            if stable_id not in alias_map.entries:
                raise HTTPException(
                    status_code=404,
                    detail=f"평가기준 stable_id={stable_id} 를 찾을 수 없습니다",
                )

            now = _now_iso_utc()
            new_entries: dict = {}
            for sid, entry in alias_map.entries.items():
                if sid == stable_id:
                    new_entries[sid] = entry.model_copy(update={
                        "status": target_status,
                        "activated_at": now if target_status == "active" else None,
                    })
                else:
                    new_entries[sid] = entry

            new_alias_map = AliasMap(
                schema_version=1, updated_at=now, entries=new_entries
            )
            cloud_write_started = True
            await alias_svc.replace(new_alias_map, old_doc_name=old_doc_name)

            # Sync DB cache for all entries
            await _sync_criteria_db_cache_from_alias_entries(
                db,
                new_entries,
                active_timestamp_override=now,
            )

            logger.info(f"상태 변경: stable_id={stable_id} status={target_status}")
            return {"stable_id": stable_id, "status": target_status}
        except HTTPException:
            raise
        except Exception as e:
            if cloud_write_started and await _recover_status_mutation_from_cloud(
                db,
                alias_svc,
                stable_id,
                target_status,
                new_alias_map,
                e,
            ):
                return {"stable_id": stable_id, "status": target_status}

            await _raise_criteria_mutation_failed(
                db,
                e,
                cloud_write_started=cloud_write_started,
            )
```

핵심: 본문 들여쓰기 한 단계 증가, 그 외 로직 동일.

- [ ] **Step 4: Run the new tests and confirm they pass**

Run:

```bash
.venv/bin/pytest tests/test_criteria_toggle_serialization.py -v
```

Expected: PASS (3/3).

- [ ] **Step 5: Run existing toggle/recovery tests to confirm no regression**

Run:

```bash
.venv/bin/pytest tests/test_admin_criteria_activate.py tests/test_criteria_activate_failure_reconcile_recovery.py -v
```

Expected: PASS 전체. (락은 단일 호출 흐름을 변경하지 않으므로 기존 테스트는 영향 없음.)

- [ ] **Step 6: Commit**

```bash
git add app/routers/admin/criteria.py tests/test_criteria_toggle_serialization.py
git commit -m "$(cat <<'EOF'
fix(criteria): serialize toggle mutations with module-level asyncio lock

alias-map upload-then-delete window causes parse conflicts when a second
mutation lands mid-flight, surfacing HTTP 503 and needs_resync to the user.
Guard _set_status_by_stable_id with a module-level asyncio.Lock so concurrent
activate/deactivate calls are serialized.

Refs: #78
EOF
)"
```

---

## Task 3: 다른 alias_map mutation 경로에도 락 적용

**Files:**
- Modify: `app/routers/admin/criteria.py` — `upload_criteria`, `delete_criteria_by_stable_id`, `replace_legacy_criteria`, `patch_criteria_alias`, `reconcile_criteria`
- Test: `tests/test_criteria_toggle_serialization.py` (확장)

토글 외 경로에서 들어오는 동시 mutation(다른 탭의 alias 편집 등)도 alias_map 다중 문서를 만들 수 있다. 동일한 `_alias_map_mutation_lock`을 5개 추가 endpoint에 공유 적용한다.

- [ ] **Step 1: Write the failing test**

`tests/test_criteria_toggle_serialization.py` 끝에 다음 테스트 추가:

```python
@pytest.mark.asyncio
async def test_alias_patch_serialized_with_toggle():
    """patch_criteria_alias 와 activate_by_stable_id 동시 호출이 직렬화된다.

    근거: alias-map 은 단일 문서이므로 alias 편집과 토글이 동시에 replace 를
    호출하면 같은 다중 문서 충돌이 발생한다.
    """
    from app.routers.admin.criteria import patch_criteria_alias

    class _AliasPatchBody:
        alias = "새이름"

    stable_id = "01HMIX"
    probe = _ConcurrencyProbe()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "fileSearchStores/s/documents/alias-map-old",
            _alias_map_with([stable_id]),
        ))
        alias.replace = AsyncMock(side_effect=probe)

        repo = repo_cls.return_value
        row = MagicMock()
        row.status = "uploaded"
        row.activated_at = None
        row.display_alias = None
        repo.get_criteria_by_stable_id = AsyncMock(return_value=row)

        db = AsyncMock()

        results = await asyncio.gather(
            activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
            patch_criteria_alias(
                stable_id=stable_id,
                body=_AliasPatchBody(),
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
        )

    assert len(results) == 2
    assert probe.calls == 2
    assert probe.max_in_progress == 1, (
        "alias 편집과 토글 사이에도 alias_svc.replace 는 직렬화되어야 한다"
    )
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run:

```bash
.venv/bin/pytest tests/test_criteria_toggle_serialization.py::test_alias_patch_serialized_with_toggle -v
```

Expected: FAIL — `probe.max_in_progress == 2` (patch_criteria_alias 가 아직 락 안에 있지 않음).

- [ ] **Step 3: Wrap `patch_criteria_alias` body in the lock**

`app/routers/admin/criteria.py` 의 `patch_criteria_alias` (현재 line 599-661):

기존 본문:

```python
async def patch_criteria_alias(
    stable_id: str,
    body: _AliasPatch,
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    cloud_write_started = False
    try:
        vec = CriteriaVectorService()
        ...
        await _raise_criteria_mutation_failed(
            db,
            e,
            cloud_write_started=cloud_write_started,
        )
```

수정 후:

```python
async def patch_criteria_alias(
    stable_id: str,
    body: _AliasPatch,
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    async with _alias_map_mutation_lock:
        cloud_write_started = False
        try:
            vec = CriteriaVectorService()
            alias_svc = CriteriaAliasMapService(
                client=vec.file_search_service.client,
                store_display_name=settings.FS_RUBRIC_STORE_NAME,
            )

            try:
                fetched = await alias_svc.fetch()
            except AliasMapParseError as e:
                await _raise_alias_map_parse_unavailable(db, e)
            if fetched is None:
                await _raise_alias_map_missing_conflict(db)
            old_doc_name, alias_map = fetched

            if stable_id not in alias_map.entries:
                raise HTTPException(
                    status_code=404,
                    detail=f"평가기준 stable_id={stable_id} 를 찾을 수 없습니다",
                )

            # Update the entry's alias only
            updated_entry = alias_map.entries[stable_id].model_copy(
                update={"alias": body.alias}
            )
            new_entries = dict(alias_map.entries)
            new_entries[stable_id] = updated_entry

            new_alias_map = AliasMap(
                schema_version=1,
                updated_at=_now_iso_utc(),
                entries=new_entries,
            )
            cloud_write_started = True
            await alias_svc.replace(new_alias_map, old_doc_name=old_doc_name)

            # Sync DB cache
            repo = CriteriaRepository(db)
            row = await repo.get_criteria_by_stable_id(stable_id)
            if row:
                row.display_alias = body.alias
                await db.commit()

            logger.info(
                f"alias 변경: stable_id={stable_id} alias={body.alias}"
            )
            return {"stable_id": stable_id, "alias": body.alias}
        except HTTPException:
            raise
        except Exception as e:
            await _raise_criteria_mutation_failed(
                db,
                e,
                cloud_write_started=cloud_write_started,
            )
```

핵심: 본문 들여쓰기 한 단계 증가, 그 외 로직 동일.

- [ ] **Step 4: Wrap `upload_criteria` body in the lock**

현재 `upload_criteria` (line 217-379) 의 본문(`temp_file_path = None ... finally: ...` 블록 전체)을 락으로 감싼다. `temp_file_path = None` 초기화부터 outer `finally` 블록까지 한 단계 들여쓰기.

기존:

```python
async def upload_criteria(
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    _sync_ready=Depends(require_criteria_sync_ready),
):
    """..."""
    temp_file_path = None
    cloud_write_started = False

    try:
        ...
    except AliasMapParseError as e:
        ...
    finally:
        # 임시 파일 삭제
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                logger.warning(
                    f"임시 파일 삭제 실패: {e}"
                )
```

수정 후:

```python
async def upload_criteria(
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    _sync_ready=Depends(require_criteria_sync_ready),
):
    """..."""
    async with _alias_map_mutation_lock:
        temp_file_path = None
        cloud_write_started = False

        try:
            ...
        except AliasMapParseError as e:
            ...
        finally:
            # 임시 파일 삭제
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception as e:
                    logger.warning(
                        f"임시 파일 삭제 실패: {e}"
                    )
```

핵심: 함수 docstring 다음부터 끝까지 전체 본문을 한 단계 더 들여쓰기. 본문 내부 로직은 변경 없음.

- [ ] **Step 5: Wrap `delete_criteria_by_stable_id` body in the lock**

현재 함수(line 387-448)의 본문(`repo = CriteriaRepository(db)` 부터 함수 끝까지)을 락으로 감싼다.

기존:

```python
async def delete_criteria_by_stable_id(
    stable_id: str,
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    repo = CriteriaRepository(db)
    row = await repo.get_criteria_by_stable_id(stable_id)
    if not row:
        raise HTTPException(...)

    cloud_write_started = False
    try:
        ...
```

수정 후:

```python
async def delete_criteria_by_stable_id(
    stable_id: str,
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    async with _alias_map_mutation_lock:
        repo = CriteriaRepository(db)
        row = await repo.get_criteria_by_stable_id(stable_id)
        if not row:
            raise HTTPException(...)

        cloud_write_started = False
        try:
            ...
```

핵심: 함수 매개변수 다음 줄부터 함수 끝까지 전체 본문을 한 단계 더 들여쓰기. 본문 내부 로직 변경 없음.

- [ ] **Step 6: Wrap `replace_legacy_criteria` body in the lock**

현재 함수(line 457-582)의 본문(`if not is_legacy_surrogate_stable_id(stable_id):` 부터 끝까지)을 락으로 감싼다.

기존:

```python
async def replace_legacy_criteria(
    stable_id: str,
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    if not is_legacy_surrogate_stable_id(stable_id):
        raise HTTPException(...)

    temp_file_path = None
    cloud_write_started = False
    try:
        ...
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            ...
```

수정 후:

```python
async def replace_legacy_criteria(
    stable_id: str,
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    async with _alias_map_mutation_lock:
        if not is_legacy_surrogate_stable_id(stable_id):
            raise HTTPException(...)

        temp_file_path = None
        cloud_write_started = False
        try:
            ...
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                ...
```

핵심: 함수 매개변수 다음 줄부터 끝까지 전체 본문 한 단계 들여쓰기. 본문 내부 로직 변경 없음. (legacy 가드도 락 안에 있음 — 가드만 통과해도 클라우드 접근 없이 빠르게 반환되므로 락 보유 시간이 사소함.)

- [ ] **Step 7: Wrap `reconcile_criteria` body in the lock**

현재 함수(line 834-864)의 본문 전체를 락으로 감싼다.

기존:

```python
async def reconcile_criteria(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """클라우드 reconcile 실행."""
    from app.config import settings
    from app.services.criteria_alias_map_service import CriteriaAliasMapService

    state_repo = AppStateRepository(db=db)
    ...
    result = await svc.reconcile()
    return {
        "ok": result.ok,
        ...
    }
```

수정 후:

```python
async def reconcile_criteria(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """클라우드 reconcile 실행."""
    async with _alias_map_mutation_lock:
        from app.config import settings
        from app.services.criteria_alias_map_service import CriteriaAliasMapService

        state_repo = AppStateRepository(db=db)
        ...
        result = await svc.reconcile()
        return {
            "ok": result.ok,
            ...
        }
```

핵심: docstring 다음부터 끝까지 한 단계 들여쓰기.

- [ ] **Step 8: Run the new alias-patch serialization test and confirm it passes**

Run:

```bash
.venv/bin/pytest tests/test_criteria_toggle_serialization.py::test_alias_patch_serialized_with_toggle -v
```

Expected: PASS.

- [ ] **Step 9: Run all criteria router tests to confirm no regression**

Run:

```bash
.venv/bin/pytest tests/test_admin_criteria_activate.py tests/test_admin_criteria_alias_patch.py tests/test_admin_criteria_alias_router.py tests/test_admin_criteria_delete_v2.py tests/test_admin_criteria_replace.py tests/test_admin_criteria_upload_v2.py tests/test_criteria_activate_failure_reconcile_recovery.py tests/test_criteria_reconciliation_v2.py -v
```

Expected: PASS 전체.

- [ ] **Step 10: Commit**

```bash
git add app/routers/admin/criteria.py tests/test_criteria_toggle_serialization.py
git commit -m "$(cat <<'EOF'
fix(criteria): extend alias-map mutation lock to upload/delete/alias/replace/reconcile

alias-map is a single cloud document. Concurrent mutations across any endpoint
(not just activate/deactivate) can produce overlapping upload-then-delete
windows. Share the existing module-level asyncio.Lock across all alias-map
mutation routes for a consistent serialization boundary.

Refs: #78
EOF
)"
```

---

## Task 4: 전체 회귀 확인

**Files:**
- 없음 (검증만)

전 테스트 스위트를 한 번 더 돌려 전체 회귀를 확인하고, 평가기준 화면의 수동 시나리오를 점검한다.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
.venv/bin/pytest -x -q
```

Expected: PASS 전체. 실패 시 해당 테스트로 돌아가 원인 진단.

- [ ] **Step 2: Manually verify the toggle UX (optional, for the implementing engineer)**

서버를 띄우고 평가기준 관리 화면에서:

1. 활성 체크박스를 빠르게 두 번 연속 클릭한다.
2. 두 번째 클릭이 disabled로 막힌다(브라우저 콘솔에서 확인 가능).
3. 라벨이 "활성 반영중…" 또는 "비활성 반영중…"으로 표시된다.
4. 응답 도착 후 라벨이 "활성"/"비활성"으로 확정되고 체크박스가 다시 enabled.
5. 상단 배너에 "⚠ 동기화 필요"가 노출되지 않는다.

> 이 단계는 surgical 원칙에 따라 자동화하지 않는다. 수동 점검만 권장.

---

## Notes

- 이 plan은 단일 uvicorn 프로세스 배포를 가정한다. 멀티 워커 환경(예: gunicorn -w N)으로 가는 경우 별도 분산 락(DB advisory 또는 Redis)을 도입해야 하며, 이는 본 plan의 범위 밖이다.
- 락 대기 자체에는 타임아웃이 없다. `alias_svc.replace()`의 60초 폴링 상한이 자연스러운 상한 역할을 하므로 추가 타임아웃은 도입하지 않는다.
- 모든 변경은 surgical하다 — 기존 recovery/optimistic update 동작은 보존된다.
