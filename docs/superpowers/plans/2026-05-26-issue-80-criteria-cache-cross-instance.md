# Issue #80 — 평가기준 cross-instance 캐시 일관성 (옵션 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 API key를 쓰는 다른 인스턴스(B)에서 A의 평가기준 업로드/상태 변경을 즉시 (목록을 열면) 반영하도록, cloud `alias_map.updated_at` 기반의 "변경 감지" 가드와 list-call 트리거 reconcile을 추가한다.

**Architecture:**
- Cloud `alias_map.updated_at` 을 "마지막으로 본 cloud 버전"으로 기록(`app_state.criteria_last_alias_map_updated_at`).
- `reconcile()`은 항상 cloud `alias_map`을 fetch한 뒤, `updated_at`이 stored와 같고 기존 조기 종료 조건도 충족하면 skip; 다르면 정상 진행한다.
- 관리자 평가기준 목록 / 사용자 대시보드 등 "활성 평가기준을 노출하는 endpoint"에 in-process 짧은 TTL throttle을 가진 fresh-cache dependency를 붙여 reconcile 호출을 유도한다.
- reconcile이 빈번해지므로 local-only 컬럼(`uploaded_by`)이 손실되지 않도록 `truncate + insert`를 stable_id 기반 upsert로 바꾼다.

**Tech Stack:** Python 3.10+, FastAPI (async), SQLAlchemy async, pytest-asyncio. 기존 `CriteriaAliasMapService` / `CriteriaReconciliationService` 위에 작은 변경.

**Decision (확정):**
- TTL throttle 기본값: 30초. `settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS`로 override 가능.
- `CRITERIA_CLOUD_RECONCILE_ENABLED=False`인 경우 새 dependency도 no-op (기존 동작 유지).
- 사용자 대시보드(`views.py:72`, `views.py:223`)에도 같은 dependency를 적용한다. (목록을 보는 모든 표면이 일관되게 신선해야 한다는 사용자 기대를 반영)
- reconcile은 `truncate + insert` 대신 stable_id upsert로 바꿔 `uploaded_by` 등 local-only 컬럼을 보존한다. (Task 3)

---

## File Structure

**Create:**
- `tests/services/test_criteria_reconciliation_updated_at_guard.py` — Task 2의 단위 테스트 (cloud `updated_at` 가드 동작)
- `tests/services/test_criteria_reconciliation_upsert.py` — Task 3의 단위 테스트 (`uploaded_by` 보존)
- `tests/test_criteria_list_triggers_reconcile.py` — Task 5/6의 endpoint dependency 통합 테스트
- `app/dependencies/criteria_freshness.py` — Task 4의 freshness dependency + throttle

**Modify:**
- `app/repositories/app_state_repository.py` — `KEY_LAST_ALIAS_MAP_UPDATED_AT` 상수 추가 (Task 1)
- `app/services/criteria_reconciliation_service.py` — 가드 확장 + upsert (Task 2, 3)
- `app/config.py` — `CRITERIA_LIST_RECONCILE_TTL_SECONDS` 추가 (Task 4)
- `app/routers/admin/criteria.py` — `list_criteria_json` 에 dependency 부착 (Task 5)
- `app/routers/admin/criteria_views.py` — HTML 목록에 dependency 부착 (Task 5)
- `app/routers/views.py` — 사용자 dashboard 라우트에 dependency 부착 (Task 6)

---

## Task 1: stored key 상수 추가

평가기준 reconcile이 "어떤 cloud `alias_map.updated_at`까지 반영되었는지" 기록할 새 키를 정의한다.

**Files:**
- Modify: `app/repositories/app_state_repository.py:11-14`
- Test: `tests/services/test_criteria_reconciliation_updated_at_guard.py` (Task 2에서 본격 작성; 이 단계에선 상수 import만 확인)

- [ ] **Step 1: 실패 테스트 작성**

`tests/services/test_criteria_reconciliation_updated_at_guard.py` 신규 작성:

```python
"""Tests for Issue #80 — cloud alias_map.updated_at 기반 reconcile guard."""


def test_key_last_alias_map_updated_at_constant_exists():
    from app.repositories.app_state_repository import (
        KEY_LAST_ALIAS_MAP_UPDATED_AT,
    )
    assert KEY_LAST_ALIAS_MAP_UPDATED_AT == "criteria_last_alias_map_updated_at"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/services/test_criteria_reconciliation_updated_at_guard.py::test_key_last_alias_map_updated_at_constant_exists -v`
Expected: FAIL — `ImportError: cannot import name 'KEY_LAST_ALIAS_MAP_UPDATED_AT'`

- [ ] **Step 3: 상수 추가**

Edit `app/repositories/app_state_repository.py:14` (마지막 키 상수 바로 아래):

```python
KEY_API_KEY_HASH = "criteria_api_key_hash"
KEY_LAST_SYNCED_AT = "criteria_last_synced_at"
KEY_SYNC_STATE = "criteria_sync_state"
KEY_SYNC_ERROR = "criteria_sync_error"
KEY_LAST_ALIAS_MAP_UPDATED_AT = "criteria_last_alias_map_updated_at"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/services/test_criteria_reconciliation_updated_at_guard.py::test_key_last_alias_map_updated_at_constant_exists -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/repositories/app_state_repository.py tests/services/test_criteria_reconciliation_updated_at_guard.py
git commit -m "feat(criteria): add KEY_LAST_ALIAS_MAP_UPDATED_AT stored key for cross-instance freshness check"
```

---

## Task 2: reconcile()에 cloud `updated_at` 가드 추가

cloud `alias_map`을 먼저 fetch하고, `updated_at`이 stored와 같으면(그리고 기존 조기 종료 조건도 충족하면) skip. 다르면 정상 진행, 성공 시 새 `updated_at`을 stored에 쓴다.

**Files:**
- Modify: `app/services/criteria_reconciliation_service.py:111-256`
- Test: `tests/services/test_criteria_reconciliation_updated_at_guard.py`

### 설계 메모

- `self._alias.fetch()`는 cloud에서 `alias_map` 문서 1개만 끌어오는 비교적 가벼운 호출이다.
- skip 조건: `not key_changed AND stored_state == "ok" AND migration_v2_done == "true" AND cloud_updated_at == stored_last_seen_updated_at`.
- cloud에 `alias_map`이 아직 없으면(`fetch() is None`) skip하지 않고 기존 로직으로 진행 (legacy migration / empty-store 케이스).
- skip 시에도 stored_state·hash 등은 그대로 둔다(추가 write 없음).
- 성공 시 `KEY_LAST_ALIAS_MAP_UPDATED_AT`을 `set_many`에 포함하여 함께 기록한다.

### 적용 위치

`app/services/criteria_reconciliation_service.py`의 `reconcile()` 메서드 내부:

- `key_changed` 계산 직후, 기존 `if (not key_changed ...): return ReconcileResult(skipped=True)` 직전에 cloud fetch + updated_at 비교 단계를 끼워 넣는다.
- 성공 분기의 `set_many` (line 238-243)에 `KEY_LAST_ALIAS_MAP_UPDATED_AT: alias_map.updated_at` 추가.

- [ ] **Step 1: 실패 테스트 작성 — skip 분기**

`tests/services/test_criteria_reconciliation_updated_at_guard.py`에 추가:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.app_state_repository import (
    KEY_API_KEY_HASH,
    KEY_LAST_ALIAS_MAP_UPDATED_AT,
    KEY_SYNC_STATE,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_reconciliation_service import (
    CriteriaReconciliationService,
    sha256_hex_of_api_key,
)


def _make_service(state_values, alias_map, list_docs):
    state = MagicMock()

    async def _get(key):
        return state_values.get(key)

    async def _set_many(items):
        state_values.update(items)

    state.get = AsyncMock(side_effect=_get)
    state.set_many = AsyncMock(side_effect=_set_many)

    alias = MagicMock()
    alias.fetch = AsyncMock(return_value=("doc/1", alias_map))
    alias.replace = AsyncMock()

    vec = MagicMock()
    vec.list_criteria_documents = AsyncMock(return_value=list_docs)

    repo = MagicMock()
    repo.truncate = AsyncMock()
    repo.insert = AsyncMock()
    repo.get_criteria_by_stable_id = AsyncMock(return_value=None)

    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    db.begin = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock()
    db.begin.return_value.__aexit__ = AsyncMock()

    return CriteriaReconciliationService(
        db=db,
        vector_service=vec,
        alias_map_service=alias,
        criteria_repo=repo,
        app_state_repo=state,
    ), vec, alias, repo


@pytest.mark.asyncio
async def test_reconcile_skips_when_cloud_updated_at_matches_stored():
    """가드 핵심 분기 — cloud의 updated_at이 stored와 같으면 list_criteria_documents 호출 없이 skip."""
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-26T00:00:00Z",
        entries={
            "sid_a": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-26T00:00:00Z",
            ),
        },
    )
    state_values = {
        KEY_API_KEY_HASH: sha256_hex_of_api_key(),
        KEY_SYNC_STATE: "ok",
        "criteria_migration_v2_done": "true",
        KEY_LAST_ALIAS_MAP_UPDATED_AT: "2026-05-26T00:00:00Z",
    }
    svc, vec, alias, repo = _make_service(state_values, alias_map, [])

    result = await svc.reconcile()

    assert result.skipped is True
    alias.fetch.assert_awaited_once()
    vec.list_criteria_documents.assert_not_awaited()
    repo.truncate.assert_not_awaited()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/services/test_criteria_reconciliation_updated_at_guard.py::test_reconcile_skips_when_cloud_updated_at_matches_stored -v`
Expected: FAIL — 현재 reconcile은 `_alias.fetch`를 가드 단계에서 호출하지 않으므로 `alias.fetch.assert_awaited_once()` 실패 또는 `vec.list_criteria_documents.assert_not_awaited()` 실패.

- [ ] **Step 3: 가드 구현**

Edit `app/services/criteria_reconciliation_service.py:111-128`. 기존 블록:

```python
    async def reconcile(self) -> ReconcileResult:
        async with alias_map_mutation_lock:
            async with _reconcile_lock:
                current_hash = sha256_hex_of_api_key()
                async with _transaction_if_needed(self._db):
                    stored_hash = await self._state.get(KEY_API_KEY_HASH)
                    stored_state = await self._state.get(KEY_SYNC_STATE)
                    migration_v2_done = await self._state.get(
                        "criteria_migration_v2_done"
                    )
                key_changed = stored_hash != current_hash

                if (
                    not key_changed
                    and stored_state == "ok"
                    and migration_v2_done == "true"
                ):
                    return ReconcileResult(skipped=True)
```

을 아래로 교체:

```python
    async def reconcile(self) -> ReconcileResult:
        async with alias_map_mutation_lock:
            async with _reconcile_lock:
                current_hash = sha256_hex_of_api_key()
                async with _transaction_if_needed(self._db):
                    stored_hash = await self._state.get(KEY_API_KEY_HASH)
                    stored_state = await self._state.get(KEY_SYNC_STATE)
                    migration_v2_done = await self._state.get(
                        "criteria_migration_v2_done"
                    )
                    stored_alias_updated_at = await self._state.get(
                        KEY_LAST_ALIAS_MAP_UPDATED_AT
                    )
                key_changed = stored_hash != current_hash

                cloud_alias_updated_at: Optional[str] = None
                fetched_for_guard = None
                if (
                    not key_changed
                    and stored_state == "ok"
                    and migration_v2_done == "true"
                    and stored_alias_updated_at is not None
                ):
                    try:
                        fetched_for_guard = await self._alias.fetch()
                    except Exception:
                        # cloud 일시 장애 시에는 skip하지 않고 기존 로직으로 진행
                        fetched_for_guard = None
                    if fetched_for_guard is not None:
                        cloud_alias_updated_at = (
                            fetched_for_guard[1].updated_at
                        )
                        if cloud_alias_updated_at == stored_alias_updated_at:
                            return ReconcileResult(skipped=True)
```

그리고 import 블록(line 18-24)을 보완해 새 상수도 가져온다:

```python
from app.repositories.app_state_repository import (
    KEY_API_KEY_HASH,
    KEY_LAST_ALIAS_MAP_UPDATED_AT,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    AppStateRepository,
)
```

그리고 성공 분기의 `set_many` 블록(line 238-243)을 교체:

```python
                        await self._state.set_many({
                            KEY_API_KEY_HASH: current_hash,
                            KEY_LAST_SYNCED_AT: _now_iso(),
                            KEY_SYNC_STATE: "ok",
                            KEY_SYNC_ERROR: None,
                            KEY_LAST_ALIAS_MAP_UPDATED_AT: alias_map.updated_at,
                        })
```

`alias_map` 변수는 이미 line 174-178의 `fetched` 블록에서 정의되어 있다 (cloud의 `alias_map`이 없으면 `empty_alias_map(_now_iso())`). 성공 분기 시점에는 reconcile이 작성/유지한 최신 `alias_map`을 가리킨다.

가드 단계에서 이미 `fetched_for_guard`를 얻었다면, line 173의 두 번째 `fetch()`를 다시 호출하지 않도록 재사용한다. 기존 코드:

```python
                    fetched = await self._alias.fetch()
```

를 교체:

```python
                    fetched = (
                        fetched_for_guard
                        if fetched_for_guard is not None
                        else await self._alias.fetch()
                    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/services/test_criteria_reconciliation_updated_at_guard.py::test_reconcile_skips_when_cloud_updated_at_matches_stored -v`
Expected: PASS

- [ ] **Step 5: 실패 테스트 추가 — proceed 분기**

`tests/services/test_criteria_reconciliation_updated_at_guard.py`에 추가:

```python
@pytest.mark.asyncio
async def test_reconcile_proceeds_when_cloud_updated_at_differs():
    """다른 인스턴스가 cloud를 갱신해 updated_at이 stored와 다르면 reconcile이 진행되어야 한다."""
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-26T01:00:00Z",  # cloud는 더 새 버전
        entries={
            "sid_a": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-26T01:00:00Z",
            ),
        },
    )
    state_values = {
        KEY_API_KEY_HASH: sha256_hex_of_api_key(),
        KEY_SYNC_STATE: "ok",
        "criteria_migration_v2_done": "true",
        KEY_LAST_ALIAS_MAP_UPDATED_AT: "2026-05-26T00:00:00Z",  # local은 옛 버전
    }
    docs = [
        {
            "document_id": "doc/sid_a",
            "display_name": "criterion-a",
            "custom_metadata_kv": {
                "type": ("criteria", []),
                "stable_id": ("sid_a", []),
                "original_title_b64": (None, []),
                "created_at": ("2026-05-26T00:50:00Z", []),
            },
        },
    ]
    svc, vec, alias, repo = _make_service(state_values, alias_map, docs)

    result = await svc.reconcile()

    assert result.ok is True
    assert result.skipped is False
    vec.list_criteria_documents.assert_awaited()
    # set_many에 새 updated_at이 기록되어야 한다
    assert state_values[KEY_LAST_ALIAS_MAP_UPDATED_AT] == "2026-05-26T01:00:00Z"


@pytest.mark.asyncio
async def test_reconcile_proceeds_on_first_run_when_stored_updated_at_missing():
    """stored가 비어 있는 최초 reconcile은 skip 분기를 우회해야 한다."""
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-26T00:00:00Z",
        entries={},
    )
    state_values = {
        KEY_API_KEY_HASH: sha256_hex_of_api_key(),
        KEY_SYNC_STATE: "ok",
        "criteria_migration_v2_done": "true",
        # KEY_LAST_ALIAS_MAP_UPDATED_AT 부재
    }
    svc, vec, alias, repo = _make_service(state_values, alias_map, [])

    result = await svc.reconcile()

    # skip 가드가 stored_alias_updated_at is None 시에는 발동하지 않으므로 진행
    assert result.skipped is False
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `pytest tests/services/test_criteria_reconciliation_updated_at_guard.py -v`
Expected: 3 PASS

- [ ] **Step 7: 회귀 테스트**

Run: `pytest tests/services/test_criteria_reconciliation_service.py tests/test_startup_reconcile.py tests/test_criteria_activate_failure_reconcile_recovery.py -v`
Expected: ALL PASS (기존 동작 유지)

- [ ] **Step 8: 커밋**

```bash
git add app/services/criteria_reconciliation_service.py tests/services/test_criteria_reconciliation_updated_at_guard.py
git commit -m "feat(criteria): gate reconcile skip on cloud alias_map.updated_at (issue #80)"
```

---

## Task 3: reconcile을 stable_id 기반 upsert로 변경 (uploaded_by 보존)

reconcile이 list-call로 자주 호출되면 기존 `truncate + insert`는 `uploaded_by`/`file_size`/`file_path` 등 local-only 컬럼을 매번 덮어쓴다. 이를 stable_id 기준 upsert로 바꿔 기존 행의 local-only 컬럼을 보존한다.

**Files:**
- Modify: `app/repositories/criteria_repository.py:371-422` (`truncate`, `insert` 주변)
- Modify: `app/services/criteria_reconciliation_service.py:211-236`
- Test: `tests/services/test_criteria_reconciliation_upsert.py`

### 설계 메모

- 새 메서드 `CriteriaRepository.upsert_from_cloud(...)`: 주어진 stable_id가 이미 있으면 cloud-소스 필드만 업데이트 (`title`, `document_id`, `display_alias`, `status`, `created_at`, `activated_at`), 없으면 신규 insert (`uploaded_by="cloud-sync"`, `file_size=0`, `file_path=""`).
- reconcile 내부에서 `truncate()` 제거. cloud `criteria_docs`의 stable_id 집합과 local 행을 비교해 cloud에 없는 local 행은 삭제.
- 새 메서드 `CriteriaRepository.delete_by_stable_ids_except(stable_ids: set[str])`: 인자 집합에 포함되지 않은 stable_id를 모두 삭제.

- [ ] **Step 1: 실패 테스트 작성**

`tests/services/test_criteria_reconciliation_upsert.py` 신규 작성:

```python
"""Tests for Issue #80 — reconcile preserves local-only columns via upsert."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.app_state_repository import (
    KEY_API_KEY_HASH,
    KEY_LAST_ALIAS_MAP_UPDATED_AT,
    KEY_SYNC_STATE,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_reconciliation_service import (
    CriteriaReconciliationService,
    sha256_hex_of_api_key,
)


@pytest.mark.asyncio
async def test_reconcile_preserves_uploaded_by_for_existing_local_rows():
    """A 인스턴스가 자기 업로드 행의 uploaded_by="alice"를 cloud-rebuild에서 잃지 않아야 한다."""
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-26T01:00:00Z",
        entries={
            "sid_a": AliasMapEntry(
                alias=None, status="active", activated_at="2026-05-26T01:00:00Z"
            ),
        },
    )
    state_values = {
        KEY_API_KEY_HASH: sha256_hex_of_api_key(),
        KEY_SYNC_STATE: "ok",
        "criteria_migration_v2_done": "true",
        KEY_LAST_ALIAS_MAP_UPDATED_AT: "2026-05-26T00:00:00Z",  # 옛 버전
    }
    docs = [
        {
            "document_id": "doc/sid_a",
            "display_name": "criterion-a",
            "custom_metadata_kv": {
                "type": ("criteria", []),
                "stable_id": ("sid_a", []),
                "original_title_b64": (None, []),
                "created_at": ("2026-05-26T00:50:00Z", []),
            },
        },
    ]

    existing_row = MagicMock()
    existing_row.uploaded_by = "alice"
    existing_row.stable_id = "sid_a"
    existing_row.file_size = 12345
    existing_row.file_path = "/local/path/a.pdf"

    state = MagicMock()
    state.get = AsyncMock(side_effect=lambda k: state_values.get(k))
    state.set_many = AsyncMock(side_effect=lambda items: state_values.update(items))

    alias = MagicMock()
    alias.fetch = AsyncMock(return_value=("doc/alias", alias_map))
    alias.replace = AsyncMock()

    vec = MagicMock()
    vec.list_criteria_documents = AsyncMock(return_value=docs)

    repo = MagicMock()
    repo.truncate = AsyncMock()
    repo.upsert_from_cloud = AsyncMock()
    repo.delete_by_stable_ids_except = AsyncMock()
    repo.get_criteria_by_stable_id = AsyncMock(return_value=existing_row)

    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    db.begin = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock()
    db.begin.return_value.__aexit__ = AsyncMock()

    svc = CriteriaReconciliationService(
        db=db,
        vector_service=vec,
        alias_map_service=alias,
        criteria_repo=repo,
        app_state_repo=state,
    )

    result = await svc.reconcile()

    assert result.ok is True
    # truncate는 더 이상 호출되면 안 된다
    repo.truncate.assert_not_awaited()
    # upsert가 호출되었고 cloud-소스 필드만 전달되었는지 확인 (uploaded_by 미포함)
    repo.upsert_from_cloud.assert_awaited()
    call_kwargs = repo.upsert_from_cloud.await_args.kwargs
    assert "uploaded_by" not in call_kwargs
    assert call_kwargs["stable_id"] == "sid_a"
    # cloud에 없는 행을 삭제하는 메서드도 호출되었는지
    repo.delete_by_stable_ids_except.assert_awaited_once()
    args, _ = repo.delete_by_stable_ids_except.call_args
    assert args[0] == {"sid_a"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/services/test_criteria_reconciliation_upsert.py -v`
Expected: FAIL — `upsert_from_cloud` 메서드가 아직 없거나 reconcile이 `truncate`를 호출함.

- [ ] **Step 3: repository 메서드 추가**

Edit `app/repositories/criteria_repository.py` — 파일 끝에 추가:

```python
    async def upsert_from_cloud(
        self,
        *,
        stable_id: str,
        document_id: str,
        title: str,
        display_alias: Optional[str],
        status: str,
        created_at: Optional[str],
        activated_at: Optional[str],
    ) -> None:
        """
        cloud truth로부터 row를 upsert. 기존 행이 있으면 cloud-소스 필드만
        업데이트하여 uploaded_by / file_size / file_path 등 local-only 컬럼을
        보존한다. 호출자가 트랜잭션을 관리한다.
        """
        existing = await self.get_criteria_by_stable_id(stable_id)
        created_dt = None
        if created_at:
            try:
                created_dt = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
            except Exception:
                created_dt = None
        activated_dt = None
        if activated_at:
            try:
                activated_dt = datetime.fromisoformat(
                    activated_at.replace("Z", "+00:00")
                )
            except Exception:
                activated_dt = None

        if existing is not None:
            existing.document_id = document_id
            existing.title = title
            existing.display_alias = display_alias
            existing.status = status
            if created_dt is not None:
                existing.created_at = created_dt
            existing.activated_at = activated_dt
            await self.db.flush()
            return

        row = Criteria(
            stable_id=stable_id,
            document_id=document_id,
            title=title,
            display_alias=display_alias,
            status=status,
            file_size=0,
            file_path="",
            uploaded_by="cloud-sync",
        )
        if created_dt is not None:
            row.created_at = created_dt
        if activated_dt is not None:
            row.activated_at = activated_dt
        self.db.add(row)
        await self.db.flush()

    async def delete_by_stable_ids_except(
        self, keep_stable_ids: set[str]
    ) -> int:
        """주어진 stable_id 집합에 없는 행을 모두 삭제. 호출자가 트랜잭션 관리."""
        if keep_stable_ids:
            stmt = delete(Criteria).where(
                Criteria.stable_id.notin_(keep_stable_ids)
            )
        else:
            stmt = delete(Criteria)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount or 0
```

- [ ] **Step 4: reconcile 호출부 교체**

Edit `app/services/criteria_reconciliation_service.py:211-236` — 기존 `truncate + insert` 블록:

```python
                    # Rebuild local DB cache
                    async with _transaction_if_needed(self._db):
                        await self._repo.truncate()
                        for d in criteria_docs:
                            sid = stable_ids_by_document[d["document_id"]]
                            entry = cleaned[sid]
                            title_b64 = (
                                _kv_string(d, "original_title_b64") or ""
                            )
                            try:
                                title = (
                                    base64.b64decode(title_b64).decode("utf-8")
                                    if title_b64
                                    else d.get("display_name") or sid
                                )
                            except Exception:
                                title = d.get("display_name") or sid
                            await self._repo.insert(
                                stable_id=sid,
                                document_id=d["document_id"],
                                title=title,
                                display_alias=entry.alias,
                                status=entry.status,
                                created_at=_kv_string(d, "created_at"),
                                activated_at=entry.activated_at,
                            )
```

을 아래로 교체:

```python
                    # Rebuild local DB cache (upsert preserves local-only cols)
                    async with _transaction_if_needed(self._db):
                        await self._repo.delete_by_stable_ids_except(
                            set(stable_ids_by_document.values())
                        )
                        for d in criteria_docs:
                            sid = stable_ids_by_document[d["document_id"]]
                            entry = cleaned[sid]
                            title_b64 = (
                                _kv_string(d, "original_title_b64") or ""
                            )
                            try:
                                title = (
                                    base64.b64decode(title_b64).decode("utf-8")
                                    if title_b64
                                    else d.get("display_name") or sid
                                )
                            except Exception:
                                title = d.get("display_name") or sid
                            await self._repo.upsert_from_cloud(
                                stable_id=sid,
                                document_id=d["document_id"],
                                title=title,
                                display_alias=entry.alias,
                                status=entry.status,
                                created_at=_kv_string(d, "created_at"),
                                activated_at=entry.activated_at,
                            )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/services/test_criteria_reconciliation_upsert.py -v`
Expected: PASS

- [ ] **Step 6: 회귀 테스트**

Run: `pytest tests/services/test_criteria_reconciliation_service.py tests/test_startup_reconcile.py tests/test_criteria_activate_failure_reconcile_recovery.py tests/services/test_criteria_reconciliation_updated_at_guard.py -v`
Expected: ALL PASS

- [ ] **Step 7: 커밋**

```bash
git add app/repositories/criteria_repository.py app/services/criteria_reconciliation_service.py tests/services/test_criteria_reconciliation_upsert.py
git commit -m "fix(criteria): preserve local-only columns (uploaded_by) via upsert in reconcile"
```

---

## Task 4: list-call 트리거 freshness dependency + throttle

관리자 목록·사용자 dashboard 같이 "활성 평가기준을 보여주는 endpoint" 진입 시, in-process 짧은 TTL throttle을 가진 dependency가 `reconcile()`을 호출한다. cloud가 안 바뀌었으면 Task 2 가드로 빨리 skip된다.

**Files:**
- Create: `app/dependencies/__init__.py`, `app/dependencies/criteria_freshness.py`
- Modify: `app/config.py:135-139`
- Test: `tests/test_criteria_freshness_dependency.py`

### 설계 메모

- 모듈 전역에서 마지막으로 freshness 체크를 한 시각(`time.monotonic()`)을 보관.
- `settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS` (기본 30) 미만 경과 시 dependency는 no-op.
- 그렇지 않으면 새 `AsyncSession`을 열어(혹은 `Depends(get_db)`로 받은 세션을 사용) `reconcile()`을 호출. 예외는 잡아서 로그만 남기고 무시 (cloud 일시 장애가 사용자 경로를 끊지 않도록).
- `CRITERIA_CLOUD_RECONCILE_ENABLED=False`이면 dependency 즉시 return.
- 이미 `app/dependencies.py` 가 모듈로 존재하므로 패키지로 바꾸지 않고, 새 파일 `app/dependencies/criteria_freshness.py` 대신 `app/services/criteria_freshness.py` 를 만든다(아래 Step 3 참조).

### Path 정정

`app/dependencies.py` 가 단일 파일이라 같은 이름의 디렉터리를 만들 수 없다. 새 모듈 위치를 **`app/services/criteria_freshness.py`** 로 정정. dependency 함수는 거기에 두고 라우터에서 import한다.

**Files (정정):**
- Create: `app/services/criteria_freshness.py`
- Test: `tests/test_criteria_freshness_dependency.py`

- [ ] **Step 1: settings 항목 추가 — 실패 테스트**

`tests/test_criteria_freshness_dependency.py` 신규 작성:

```python
"""Tests for Issue #80 — list-call triggered freshness dependency."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest


def test_settings_has_list_reconcile_ttl():
    from app.config import settings
    assert isinstance(settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS, int)
    assert settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS >= 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_criteria_freshness_dependency.py::test_settings_has_list_reconcile_ttl -v`
Expected: FAIL — `AttributeError` for `CRITERIA_LIST_RECONCILE_TTL_SECONDS`.

- [ ] **Step 3: settings 추가**

Edit `app/config.py:135-139` 주변, `CRITERIA_CLOUD_RECONCILE_ENABLED` 아래에 추가:

```python
    CRITERIA_LIST_RECONCILE_TTL_SECONDS: int = Field(
        default=30,
        description=(
            "평가기준 목록 endpoint에서 cloud freshness를 확인하는 "
            "최소 간격(초). 0이면 매 요청마다 확인."
        ),
    )
```

- [ ] **Step 4: settings 테스트 통과 확인**

Run: `pytest tests/test_criteria_freshness_dependency.py::test_settings_has_list_reconcile_ttl -v`
Expected: PASS

- [ ] **Step 5: dependency 실패 테스트 작성**

`tests/test_criteria_freshness_dependency.py`에 추가:

```python
@pytest.mark.asyncio
async def test_freshness_dependency_calls_reconcile_when_ttl_expired(monkeypatch):
    from app.services import criteria_freshness as cf

    cf._reset_throttle_for_test()
    monkeypatch.setattr(
        cf.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True
    )
    monkeypatch.setattr(
        cf.settings, "CRITERIA_LIST_RECONCILE_TTL_SECONDS", 0
    )

    with patch.object(
        cf, "_run_reconcile_once", new=AsyncMock()
    ) as run:
        await cf.ensure_criteria_cache_fresh()
        await cf.ensure_criteria_cache_fresh()
    assert run.await_count == 2


@pytest.mark.asyncio
async def test_freshness_dependency_throttles_within_ttl(monkeypatch):
    from app.services import criteria_freshness as cf

    cf._reset_throttle_for_test()
    monkeypatch.setattr(
        cf.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True
    )
    monkeypatch.setattr(
        cf.settings, "CRITERIA_LIST_RECONCILE_TTL_SECONDS", 60
    )

    with patch.object(
        cf, "_run_reconcile_once", new=AsyncMock()
    ) as run:
        await cf.ensure_criteria_cache_fresh()
        await cf.ensure_criteria_cache_fresh()
        await cf.ensure_criteria_cache_fresh()
    assert run.await_count == 1


@pytest.mark.asyncio
async def test_freshness_dependency_noop_when_reconcile_disabled(monkeypatch):
    from app.services import criteria_freshness as cf

    cf._reset_throttle_for_test()
    monkeypatch.setattr(
        cf.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", False
    )
    monkeypatch.setattr(
        cf.settings, "CRITERIA_LIST_RECONCILE_TTL_SECONDS", 0
    )

    with patch.object(
        cf, "_run_reconcile_once", new=AsyncMock()
    ) as run:
        await cf.ensure_criteria_cache_fresh()
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_freshness_dependency_swallows_exceptions(monkeypatch, caplog):
    from app.services import criteria_freshness as cf

    cf._reset_throttle_for_test()
    monkeypatch.setattr(
        cf.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True
    )
    monkeypatch.setattr(
        cf.settings, "CRITERIA_LIST_RECONCILE_TTL_SECONDS", 0
    )

    async def boom():
        raise RuntimeError("cloud 503")

    with patch.object(cf, "_run_reconcile_once", new=boom):
        await cf.ensure_criteria_cache_fresh()  # raises 안 되어야 함
```

- [ ] **Step 6: 테스트 실패 확인**

Run: `pytest tests/test_criteria_freshness_dependency.py -v`
Expected: 4 FAIL — `ImportError: cannot import 'criteria_freshness'`.

- [ ] **Step 7: dependency 구현**

`app/services/criteria_freshness.py` 신규 작성:

```python
"""
Issue #80 — 평가기준 목록 endpoint에서 cloud freshness를 lazy하게 확인.

list 호출 시점에 in-process throttle을 거쳐 reconcile()을 호출한다. cloud의
alias_map.updated_at이 안 바뀌었다면 reconcile은 Task 2 가드로 빠르게 skip된다.
다른 인스턴스가 cloud를 갱신했다면 local cache가 자동으로 따라잡는다.

원칙:
- cloud 호출 실패는 사용자 경로를 끊지 않는다 (로그만 남기고 무시).
- CRITERIA_CLOUD_RECONCILE_ENABLED=False 시 dependency는 no-op.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

_throttle_lock = asyncio.Lock()
_last_check_monotonic: Optional[float] = None


def _reset_throttle_for_test() -> None:
    """테스트 전용 — throttle 상태 초기화."""
    global _last_check_monotonic
    _last_check_monotonic = None


async def _run_reconcile_once() -> None:
    """새 세션에서 reconcile을 1회 실행."""
    from app.db import async_session_maker
    from app.repositories.app_state_repository import AppStateRepository
    from app.repositories.criteria_repository import CriteriaRepository
    from app.services.criteria_alias_map_service import (
        CriteriaAliasMapService,
    )
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )
    from app.services.criteria_vector_service import CriteriaVectorService

    async with async_session_maker() as db:
        vec = CriteriaVectorService()
        alias = CriteriaAliasMapService(
            client=vec.file_search_service.client,
            store_display_name=settings.FS_RUBRIC_STORE_NAME,
        )
        svc = CriteriaReconciliationService(
            db=db,
            vector_service=vec,
            alias_map_service=alias,
            criteria_repo=CriteriaRepository(db=db),
            app_state_repo=AppStateRepository(db=db),
        )
        await svc.reconcile()
        await db.commit()


async def ensure_criteria_cache_fresh() -> None:
    """FastAPI Depends() 대상 — list endpoint 진입 시 호출."""
    global _last_check_monotonic

    if not settings.CRITERIA_CLOUD_RECONCILE_ENABLED:
        return

    ttl = settings.CRITERIA_LIST_RECONCILE_TTL_SECONDS
    now = time.monotonic()

    async with _throttle_lock:
        if (
            _last_check_monotonic is not None
            and ttl > 0
            and (now - _last_check_monotonic) < ttl
        ):
            return
        _last_check_monotonic = now

    try:
        await _run_reconcile_once()
    except Exception:
        logger.warning(
            "평가기준 freshness 확인 실패 (cache 그대로 응답)",
            exc_info=True,
        )
```

- [ ] **Step 8: 테스트 통과 확인**

Run: `pytest tests/test_criteria_freshness_dependency.py -v`
Expected: 5 PASS (settings + 4 dependency cases)

- [ ] **Step 9: 커밋**

```bash
git add app/config.py app/services/criteria_freshness.py tests/test_criteria_freshness_dependency.py
git commit -m "feat(criteria): add list-triggered freshness dependency with TTL throttle (issue #80)"
```

---

## Task 5: 관리자 평가기준 목록 endpoint에 dependency 부착

**Files:**
- Modify: `app/routers/admin/criteria.py:817-849`
- Modify: `app/routers/admin/criteria_views.py:75-113`
- Test: `tests/test_criteria_list_triggers_reconcile.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_criteria_list_triggers_reconcile.py` 신규 작성:

```python
"""Issue #80 — 평가기준 목록 endpoint가 freshness dependency를 호출하는지 검증."""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_admin_list_json_triggers_freshness_check(client_admin):
    """GET /admin/criteria 진입 시 ensure_criteria_cache_fresh가 호출되어야 한다."""
    with patch(
        "app.services.criteria_freshness.ensure_criteria_cache_fresh",
        new=AsyncMock(),
    ) as ensure:
        resp = await client_admin.get("/admin/criteria")
    assert resp.status_code == 200
    ensure.assert_awaited()


@pytest.mark.asyncio
async def test_admin_list_html_triggers_freshness_check(client_admin):
    with patch(
        "app.services.criteria_freshness.ensure_criteria_cache_fresh",
        new=AsyncMock(),
    ) as ensure:
        resp = await client_admin.get("/admin/criteria/")  # HTML view path
    assert resp.status_code == 200
    ensure.assert_awaited()
```

테스트가 사용하는 `client_admin` 픽스처는 `tests/conftest.py`의 기존 admin client 픽스처를 그대로 따른다. 이름이 다를 경우 `tests/conftest.py`를 읽어 그에 맞춰 fixture 이름을 교체.

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_criteria_list_triggers_reconcile.py -v`
Expected: FAIL — dependency가 아직 부착되지 않음.

- [ ] **Step 3: 라우터에 dependency 추가**

Edit `app/routers/admin/criteria.py:817-822` — 기존:

```python
@router.get(
    "",
    summary="평가기준 목록 (JSON)",
    description="평가기준 목록과 클라우드 동기화 상태를 반환합니다.",
)
async def list_criteria_json(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
```

을:

```python
@router.get(
    "",
    summary="평가기준 목록 (JSON)",
    description="평가기준 목록과 클라우드 동기화 상태를 반환합니다.",
)
async def list_criteria_json(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    _fresh=Depends(ensure_criteria_cache_fresh),
):
```

파일 상단 import 추가:

```python
from app.services.criteria_freshness import ensure_criteria_cache_fresh
```

Edit `app/routers/admin/criteria_views.py:75-113` — HTML 라우트도 같은 방식으로 `_fresh=Depends(ensure_criteria_cache_fresh)`를 시그니처에 추가하고 같은 import를 파일 상단에 추가.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_criteria_list_triggers_reconcile.py -v`
Expected: PASS (2)

- [ ] **Step 5: 회귀 — 라우터/관리 테스트**

Run: `pytest tests/ -k "admin_criteria" -v`
Expected: ALL PASS

- [ ] **Step 6: 커밋**

```bash
git add app/routers/admin/criteria.py app/routers/admin/criteria_views.py tests/test_criteria_list_triggers_reconcile.py
git commit -m "feat(criteria): trigger freshness check on admin criteria list endpoints (issue #80)"
```

---

## Task 6: 사용자 dashboard에도 dependency 부착

사용자 대시보드는 `get_active_criteria()`로 활성 평가기준 목록을 표시한다(`views.py:72`, `views.py:223`). cross-instance 일관성을 위해 같은 dependency를 부착한다.

**Files:**
- Modify: `app/routers/views.py` (대시보드 GET 라우트 시그니처, upload 후 dashboard 렌더 라우트)
- Test: `tests/test_criteria_list_triggers_reconcile.py` (Task 5에서 만든 파일에 케이스 추가)

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_criteria_list_triggers_reconcile.py`에 추가:

```python
@pytest.mark.asyncio
async def test_user_dashboard_triggers_freshness_check(client_user):
    with patch(
        "app.services.criteria_freshness.ensure_criteria_cache_fresh",
        new=AsyncMock(),
    ) as ensure:
        resp = await client_user.get("/dashboard")
    assert resp.status_code == 200
    ensure.assert_awaited()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_criteria_list_triggers_reconcile.py::test_user_dashboard_triggers_freshness_check -v`
Expected: FAIL

- [ ] **Step 3: 라우트에 dependency 추가**

Edit `app/routers/views.py`의 `/dashboard` GET 라우트 시그니처에 `_fresh=Depends(ensure_criteria_cache_fresh)`를 추가. upload 후 dashboard를 렌더하는 라우트도 동일.

파일 상단 import 추가:

```python
from app.services.criteria_freshness import ensure_criteria_cache_fresh
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_criteria_list_triggers_reconcile.py -v`
Expected: ALL PASS

- [ ] **Step 5: 전체 회귀**

Run: `pytest tests/ -q`
Expected: 기존 PASS 카운트 + 새 테스트 PASS. 실패 시 해당 테스트의 root cause를 확인하고 픽스처/path 조정.

- [ ] **Step 6: 커밋**

```bash
git add app/routers/views.py tests/test_criteria_list_triggers_reconcile.py
git commit -m "feat(criteria): trigger freshness check on user dashboard (issue #80)"
```

---

## Task 7: 수동 검증 + 이슈 닫기 준비

자동화 테스트만으로는 cross-instance 시나리오를 완전히 보장하기 어렵다. 두 프로세스를 띄워 실제 cloud로 검증한다.

- [ ] **Step 1: 두 인스턴스 기동**

```bash
# Terminal 1
uvicorn app.main:app --port 8000

# Terminal 2 (다른 SQLite 파일이지만 같은 GOOGLE_API_KEY)
DATABASE_URL=sqlite+aiosqlite:///./data/app_b.db uvicorn app.main:app --port 8001
```

- [ ] **Step 2: A(:8000) 관리자로 로그인 → 평가기준 1건 업로드**

- [ ] **Step 3: B(:8001) 관리자로 로그인 → `/admin/criteria` 열기**

기대: 30초 throttle 경과 후(혹은 `CRITERIA_LIST_RECONCILE_TTL_SECONDS=0`으로 띄웠다면 즉시) A에서 업로드한 평가기준이 보임.

- [ ] **Step 4: B의 활성/비활성 토글 → A에서 새로고침**

기대: A 목록의 상태가 업데이트됨.

- [ ] **Step 5: B가 A의 행 삭제 → A에서 새로고침**

기대: A에서도 해당 행이 사라짐.

- [ ] **Step 6: A의 `uploaded_by` 값이 reconcile 후에도 보존되는지 확인**

기대: A의 자기 업로드 행은 `uploaded_by=<admin_a>`를 유지. B에서 cloud-sync로 들어온 행은 `uploaded_by="cloud-sync"`.

- [ ] **Step 7: 검증 결과를 issue #80에 코멘트**

```bash
gh issue comment 80 --body "검증 완료: A↔B 양방향 업로드/토글/삭제 반영 확인. uploaded_by 보존 확인."
```

- [ ] **Step 8: PR 생성**

```bash
gh pr create --title "fix(criteria): cross-instance cache freshness via cloud alias_map.updated_at (#80)" \
  --body "Closes #80. See docs/superpowers/plans/2026-05-26-issue-80-criteria-cache-cross-instance.md"
```

---

## Self-Review 체크

- 스펙(issue #80) 커버리지:
  - "B에서도 A의 업로드가 검색되어야 함" → Task 4-6 (list endpoint 트리거).
  - "재시작해도 안 보임" → Task 2 (cloud `updated_at` 가드가 기존 skip을 해소).
  - "수정 방향 옵션 1: list 조회 시 cloud `alias_map.updated_at` 확인 → reconcile 트리거 + 조기 종료 가드 확장" → Task 2 + Task 4 양쪽으로 분담.
- Placeholder/TBD 없음 확인.
- 타입/시그니처 일관:
  - `upsert_from_cloud(stable_id, document_id, title, display_alias, status, created_at, activated_at)` — Task 3에서 정의하고 동일 시그니처로 reconcile에서 호출.
  - `delete_by_stable_ids_except(keep: set[str])` — 동일.
  - `ensure_criteria_cache_fresh()` — Task 4 정의, Task 5/6에서 동일 이름으로 import.
  - `KEY_LAST_ALIAS_MAP_UPDATED_AT` — Task 1 정의, Task 2에서 동일 이름으로 사용.

## Open Decisions (실행 전 사용자 확정 필요)

1. **TTL 기본값**: 30초 (현 계획). 더 짧게/길게 가져갈지 결정 필요. 0이면 매 요청마다 cloud fetch.
2. **사용자 dashboard에도 dependency 적용 여부**: 현 계획은 YES (Task 6). 사용자 트래픽이 많아 cloud cost가 부담되면 admin 페이지에만 부착으로 축소 가능.
3. **Task 3 (upsert/uploaded_by 보존) 포함 여부**: 현 계획은 YES. 이 변경은 reconcile이 잦아지면 필수적이지만, 기존 truncate 동작을 유지하고 `uploaded_by` 클로버를 수용하기로 한다면 Task 3을 빼도 됨.

위 3개 결정에 변경이 있으면 알려주세요. 그대로면 Task 1부터 순서대로 진행 가능합니다.
