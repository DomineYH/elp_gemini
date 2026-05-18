# Criteria Status Mutation Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 평가기준 활성/비활성 요청에서 클라우드 alias-map 변경이 실제로 반영됐는데도 API가 500을 반환하는 문제를 제거한다.

**Architecture:** `activate`/`deactivate`는 alias-map을 cloud truth로 쓰고 local DB는 캐시로 유지한다. `alias_svc.replace()` 또는 이후 DB commit이 실패하면 곧바로 실패로 확정하지 말고 alias-map을 다시 읽어 요청한 상태가 클라우드에 반영됐는지 확인한다. 클라우드에 반영된 경우 local DB 캐시를 갱신하고 정상 응답을 반환하며, 반영되지 않은 경우에만 기존처럼 `needs_resync`로 마킹하고 500을 반환한다.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy AsyncSession, pytest, pytest-asyncio, unittest.mock.

---

## Problem Summary

현재 흐름:

1. `app/routers/admin/criteria.py::_set_status_by_stable_id()`가 alias-map entry의 `status`를 변경한다.
2. `cloud_write_started = True`로 둔 뒤 `CriteriaAliasMapService.replace()`를 호출한다.
3. `replace()`는 새 alias-map document를 업로드하고, polling 후 기존 alias-map document를 삭제한다.
4. upload response, operation polling timeout, old document delete, 또는 이후 DB commit 중 예외가 나면 outer `except Exception`에서 500을 반환한다.
5. 이미 클라우드에 새 alias-map이 올라간 경우에도 응답은 500이다.
6. 사용자가 "재동기화"를 누르면 reconcile이 클라우드 alias-map을 읽어 DB를 rebuild하므로 활성/비활성 상태가 뒤늦게 적용된 것처럼 보인다.

수정 원칙:

- 클라우드 alias-map의 `updated_at`과 대상 entry가 이번 요청에서 만든 alias-map과 일치하고, 대상 entry가 요청 상태를 포함할 때만 성공으로 복구한다.
- 클라우드 alias-map이 이번 요청에서 만든 alias-map 반영을 증명하지 못하면 기존 실패 처리와 동일하게 `needs_resync`를 남긴다.
- `CriteriaAliasMapService.replace()`의 upload-then-delete 순서는 유지한다.
- 프론트엔드 변경 없이 API 결과만 안정화한다.

## File Structure

- Modify: `app/routers/admin/criteria.py`
  - Add small DB cache sync helper.
  - Add cloud recovery helper for status mutation failures.
  - Use helper in `_set_status_by_stable_id()`.
- Modify: `tests/test_admin_criteria_activate.py`
  - Add regression tests for activate/deactivate recovery after ambiguous cloud publish failure.
  - Preserve existing unrecovered-failure tests.
- Optional read-only reference: `tests/test_criteria_activate_failure_reconcile_recovery.py`
  - Existing diagnostic test file in the workspace. Do not depend on it as the only regression coverage because it is currently untracked.

---

### Task 1: Add Failing Recovery Tests

**Files:**
- Modify: `tests/test_admin_criteria_activate.py`

- [ ] **Step 1: Add activate recovery test**

Append this test after `test_activate_replace_failure_marks_resync()`:

```python
@pytest.mark.asyncio
async def test_activate_replace_failure_recovers_when_cloud_has_target_status():
    db = AsyncMock()
    stable_id = "01HACTIVE"
    row = MagicMock(status="uploaded", activated_at=None)

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(side_effect=[
            (
                "docs/alias-map-old",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:00Z",
                    entries={
                        stable_id: AliasMapEntry(
                            alias=None,
                            status="uploaded",
                            activated_at=None,
                        ),
                    },
                ),
            ),
            (
                "docs/alias-map-new",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:01Z",
                    entries={
                        stable_id: AliasMapEntry(
                            alias=None,
                            status="active",
                            activated_at="2026-05-15T00:00:01Z",
                        ),
                    },
                ),
            ),
        ])
        alias.replace = AsyncMock(
            side_effect=TimeoutError("alias-map upload timeout")
        )
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=row
        )
        state = state_cls.return_value
        state.set = AsyncMock()

        result = await activate_by_stable_id(
            stable_id=stable_id,
            current_admin=object(),
            _sync_ready=None,
            db=db,
        )

    assert result == {"stable_id": stable_id, "status": "active"}
    assert row.status == "active"
    assert row.activated_at is not None
    alias.replace.assert_awaited_once()
    assert alias.fetch.await_count == 2
    db.rollback.assert_awaited_once()
    db.commit.assert_awaited_once()
    state.set.assert_not_awaited()
```

- [ ] **Step 2: Add deactivate recovery test**

Append this test after the activate recovery test:

```python
@pytest.mark.asyncio
async def test_deactivate_replace_failure_recovers_when_cloud_has_target_status():
    db = AsyncMock()
    stable_id = "01HDEACTIVE"
    row = MagicMock(
        status="active",
        activated_at="2026-05-15T00:00:00Z",
    )

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(side_effect=[
            (
                "docs/alias-map-old",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:00Z",
                    entries={
                        stable_id: AliasMapEntry(
                            alias=None,
                            status="active",
                            activated_at="2026-05-15T00:00:00Z",
                        ),
                    },
                ),
            ),
            (
                "docs/alias-map-new",
                AliasMap(
                    schema_version=1,
                    updated_at="2026-05-15T00:00:01Z",
                    entries={
                        stable_id: AliasMapEntry(
                            alias=None,
                            status="uploaded",
                            activated_at=None,
                        ),
                    },
                ),
            ),
        ])
        alias.replace = AsyncMock(
            side_effect=RuntimeError("old alias-map delete failed")
        )
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=row
        )
        state = state_cls.return_value
        state.set = AsyncMock()

        result = await deactivate_by_stable_id(
            stable_id=stable_id,
            current_admin=object(),
            _sync_ready=None,
            db=db,
        )

    assert result == {"stable_id": stable_id, "status": "uploaded"}
    assert row.status == "uploaded"
    assert row.activated_at is None
    alias.replace.assert_awaited_once()
    assert alias.fetch.await_count == 2
    db.rollback.assert_awaited_once()
    db.commit.assert_awaited_once()
    state.set.assert_not_awaited()
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run pytest tests/test_admin_criteria_activate.py -q
```

Expected: the two new tests fail with `HTTPException: 500` because the route does not yet recover after `alias.replace()` raises.

- [ ] **Step 4: Commit tests**

```bash
git add tests/test_admin_criteria_activate.py
git commit -m "test(criteria): cover status mutation cloud publish recovery"
```

---

### Task 2: Extract DB Cache Sync Helper

**Files:**
- Modify: `app/routers/admin/criteria.py`
- Test: `tests/test_admin_criteria_activate.py`

- [ ] **Step 1: Add helper below `_raise_criteria_mutation_failed()`**

Insert this function in `app/routers/admin/criteria.py` after `_raise_criteria_mutation_failed()`:

```python
async def _sync_criteria_db_cache_from_alias_entries(
    db: AsyncSession,
    entries: dict[str, AliasMapEntry],
) -> None:
    repo = CriteriaRepository(db)
    for sid, entry in entries.items():
        row = await repo.get_criteria_by_stable_id(sid)
        if row:
            row.status = entry.status
            row.activated_at = (
                _parse_iso(entry.activated_at)
                if entry.status == "active"
                else None
            )
    await db.commit()
```

- [ ] **Step 2: Replace inline DB sync in `_set_status_by_stable_id()`**

Replace this block:

```python
        # Sync DB cache for all entries
        repo = CriteriaRepository(db)
        parsed_now = _parse_iso(now)
        for sid, entry in new_entries.items():
            row = await repo.get_criteria_by_stable_id(sid)
            if row:
                row.status = entry.status
                row.activated_at = (
                    parsed_now if entry.status == "active" else None
                )
        await db.commit()
```

with:

```python
        # Sync DB cache for all entries
        await _sync_criteria_db_cache_from_alias_entries(db, new_entries)
```

- [ ] **Step 3: Run focused activation tests**

Run:

```bash
PYTHONPATH=. uv run pytest tests/test_admin_criteria_activate.py -q
```

Expected: existing tests still pass except the two new recovery tests from Task 1, which still fail until Task 3.

- [ ] **Step 4: Commit helper refactor**

```bash
git add app/routers/admin/criteria.py
git commit -m "refactor(criteria): share alias-map DB cache sync"
```

---

### Task 3: Recover Successful Cloud Writes After Exceptions

**Files:**
- Modify: `app/routers/admin/criteria.py`
- Test: `tests/test_admin_criteria_activate.py`

- [ ] **Step 1: Add recovery helper below DB sync helper**

Insert this function below `_sync_criteria_db_cache_from_alias_entries()`:

```python
async def _recover_status_mutation_from_cloud(
    db: AsyncSession,
    alias_svc: CriteriaAliasMapService,
    stable_id: str,
    target_status: str,
    expected_alias_map: AliasMap,
    exc: Exception,
) -> bool:
    try:
        await db.rollback()
    except Exception:
        logger.warning(
            "평가기준 상태 변경 복구 전 rollback 실패",
            exc_info=True,
        )

    try:
        fetched = await alias_svc.fetch()
    except Exception:
        logger.warning(
            "평가기준 상태 변경 실패 후 alias_map 재조회 실패",
            exc_info=True,
        )
        return False

    if fetched is None:
        return False

    _, cloud_alias_map = fetched
    expected_entry = expected_alias_map.entries.get(stable_id)
    entry = cloud_alias_map.entries.get(stable_id)
    if (
        cloud_alias_map.updated_at != expected_alias_map.updated_at
        or expected_entry is None
        or entry is None
        or entry != expected_entry
        or entry.status != target_status
    ):
        return False

    try:
        await _sync_criteria_db_cache_from_alias_entries(
            db,
            cloud_alias_map.entries,
        )
    except Exception:
        logger.warning(
            "평가기준 상태 변경 cloud 반영 후 DB 캐시 복구 실패",
            exc_info=True,
        )
        return False

    logger.info(
        "평가기준 상태 변경 예외 후 cloud truth 기준 복구: "
        "stable_id=%s status=%s original_error=%s",
        stable_id,
        target_status,
        exc,
    )
    return True
```

- [ ] **Step 2: Use recovery helper in `_set_status_by_stable_id()`**

Replace the final `except Exception` block:

```python
    except Exception as e:
        await _raise_criteria_mutation_failed(
            db,
            e,
            cloud_write_started=cloud_write_started,
        )
```

with:

```python
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

- [ ] **Step 3: Run focused activation tests**

Run:

```bash
PYTHONPATH=. uv run pytest tests/test_admin_criteria_activate.py -q
```

Expected: all non-skipped tests in `tests/test_admin_criteria_activate.py` pass.

- [ ] **Step 4: Commit recovery implementation**

```bash
git add app/routers/admin/criteria.py
git commit -m "fix(criteria): recover status mutations from cloud alias-map"
```

---

### Task 4: Add Explicit Unrecovered Failure Guard Test

**Files:**
- Modify: `tests/test_admin_criteria_activate.py`

- [ ] **Step 1: Add a test proving old behavior remains for uncommitted cloud writes**

Append this test after the recovery tests:

```python
@pytest.mark.asyncio
async def test_activate_replace_failure_still_marks_resync_when_cloud_unchanged():
    db = AsyncMock()
    stable_id = "01HACTIVE"

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        old_alias_map = AliasMap(
            schema_version=1,
            updated_at="2026-05-15T00:00:00Z",
            entries={
                stable_id: AliasMapEntry(
                    alias=None,
                    status="uploaded",
                    activated_at=None,
                ),
            },
        )
        alias.fetch = AsyncMock(side_effect=[
            ("docs/alias-map", old_alias_map),
            ("docs/alias-map", old_alias_map),
        ])
        alias.replace = AsyncMock(
            side_effect=RuntimeError("upload_to_file_search_store 503")
        )

        state = state_cls.return_value
        state.set = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )

    assert exc_info.value.status_code == 500
    assert alias.fetch.await_count == 2
    alias.replace.assert_awaited_once()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")
```

- [ ] **Step 2: Run the explicit guard test**

Run:

```bash
PYTHONPATH=. uv run pytest tests/test_admin_criteria_activate.py::test_activate_replace_failure_still_marks_resync_when_cloud_unchanged -q
```

Expected: PASS.

- [ ] **Step 3: Run the whole activation test file**

Run:

```bash
PYTHONPATH=. uv run pytest tests/test_admin_criteria_activate.py -q
```

Expected: all non-skipped tests pass.

- [ ] **Step 4: Commit guard test**

```bash
git add tests/test_admin_criteria_activate.py
git commit -m "test(criteria): keep resync marker when status publish is not committed"
```

---

### Task 5: Verify Against Existing Reconcile and Alias-Map Coverage

**Files:**
- No code changes expected.

- [ ] **Step 1: Run the status mutation and alias-map tests**

Run:

```bash
PYTHONPATH=. uv run pytest \
  tests/test_admin_criteria_activate.py \
  tests/test_criteria_alias_map_service_replace.py \
  tests/test_criteria_reconciliation_v2.py \
  tests/routers/test_criteria_router_sync.py \
  -q
```

Expected: PASS, with the same skipped structural tests as before.

- [ ] **Step 2: Run the diagnostic reproduction test if present**

Run:

```bash
PYTHONPATH=. uv run pytest tests/test_criteria_activate_failure_reconcile_recovery.py -q
```

Expected: PASS if the file exists. If the file is absent in a clean checkout, skip this command and rely on the committed tests in `tests/test_admin_criteria_activate.py`.

- [ ] **Step 3: Check worktree**

Run:

```bash
git status --short
```

Expected: only intentional changes remain. Do not add unrelated untracked files such as `tests/AGENTS.md` unless the user explicitly asks.

- [ ] **Step 4: Commit verification-only changes if any**

If Task 5 produced no code changes, do not commit. If a test needed a small correction, commit only that correction:

```bash
git add tests/test_admin_criteria_activate.py app/routers/admin/criteria.py
git commit -m "test(criteria): verify status mutation recovery suite"
```

---

## Manual Verification

After implementation, use the admin UI:

1. Open the criteria list page.
2. Activate an uploaded criterion.
3. Deactivate an active criterion.
4. Confirm the UI does not show a 500 error when the cloud alias-map already contains the requested state.
5. Confirm the sync badge remains normal after successful recovered mutations.
6. Simulate a real cloud outage by forcing `alias_svc.replace()` to fail before commit in a local test or staging environment; confirm the UI still shows the resync state instead of silently reporting success.

## Self-Review

- Spec coverage: The plan covers the reported 500-after-success case, preserves the existing resync path for uncommitted cloud failures, and avoids changing the frontend.
- Placeholder scan: No implementation step uses placeholder language. Every changed code block is included.
- Type consistency: Helpers use existing `AsyncSession`, `AliasMapEntry`, `CriteriaAliasMapService`, `CriteriaRepository`, `_parse_iso()`, and logger names already present in `app/routers/admin/criteria.py`.
