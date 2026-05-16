# Issue #60: alias_map Chunk-Size Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `criteria_reconciliation_service.reconcile()` from failing with `400 INVALID_ARGUMENT (StringList value > 256 chars)` so that pre-v2 criteria documents become visible in the admin UI.

**Architecture:** Google File Search API rejects any value inside `custom_metadata[*].string_list_value.values[i]` that exceeds 256 characters. Two constants in this codebase (`alias_map_codec._CHUNK_SIZE` and `file_search_service._MANIFEST_PAYLOAD_CHUNK_SIZE`) are documented to be identical and currently both set to `3000`, which violates the limit whenever the alias_map payload is large enough to require multi-chunk encoding. The fix lowers both constants to a safe value (240) and adds three layers of regression coverage: codec-level chunk bound, SDK-mock enforcement of the 256-char API rule, and an integration test that exercises the full reconcile path with synthesized legacy-surrogate entries (the exact scenario that triggered the production failure).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, google-genai SDK, pytest + pytest-asyncio.

---

### Task 1: Lower codec chunk size to satisfy the 256-char API limit

**Files:**
- Modify: `app/services/alias_map_codec.py:16`
- Modify: `tests/test_alias_map_codec.py:21-26` (existing bound assertion needs to match the new constant)

- [ ] **Step 1: Add a failing regression test for the 256-char API limit**

Append the following test to `tests/test_alias_map_codec.py` (keep the existing tests intact):

```python
def test_chunks_respect_file_search_string_list_value_limit():
    """Google File Search rejects string_list_value entries > 256 chars (issue #60)."""
    # Force multi-chunk by encoding a payload that won't fit in a single chunk.
    big = {
        "schema_version": 1,
        "entries": {
            f"id{i}": {"alias": "한" * 100, "status": "uploaded"}
            for i in range(50)
        },
    }
    chunks = encode_alias_map_payload(big)
    assert len(chunks) > 1, "test setup must produce multi-chunk output"
    longest = max(len(c) for c in chunks)
    assert longest <= 256, (
        f"chunk length {longest} exceeds Google File Search "
        f"string_list_value 256-char limit"
    )
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run: `pytest tests/test_alias_map_codec.py::test_chunks_respect_file_search_string_list_value_limit -v`
Expected: FAIL with `AssertionError: chunk length 3000 exceeds Google File Search string_list_value 256-char limit`

- [ ] **Step 3: Lower the codec constant**

In `app/services/alias_map_codec.py`, change line 16:

```python
# Google File Search caps each string_list_value entry at 256 chars (issue #60).
# Keep in sync with file_search_service._MANIFEST_PAYLOAD_CHUNK_SIZE.
_CHUNK_SIZE = 240
```

- [ ] **Step 4: Update the existing chunk-bound assertion**

In `tests/test_alias_map_codec.py`, update `test_chunks_are_bounded` so its bound matches the real API constraint instead of the old 3000 value:

```python
def test_chunks_are_bounded():
    # 10KB of Korean text
    big = {"entries": {"id1": {"alias": "한" * 10_000, "status": "uploaded"}}}
    chunks = encode_alias_map_payload(big)
    assert all(len(c) <= 256 for c in chunks)
    assert decode_alias_map_payload(chunks)["entries"]["id1"]["alias"] == "한" * 10_000
```

- [ ] **Step 5: Run the full codec test module and confirm both tests pass**

Run: `pytest tests/test_alias_map_codec.py -v`
Expected: PASS (all 4 tests, including the new one)

- [ ] **Step 6: Commit**

```bash
git add app/services/alias_map_codec.py tests/test_alias_map_codec.py
git commit -m "fix(criteria-meta): cap alias_map payload chunks at 240 chars (issue #60)

Google File Search rejects custom_metadata[*].string_list_value.values[i]
longer than 256 chars; the previous 3000-char chunking made every
alias_map upload fail with 400 INVALID_ARGUMENT as soon as the payload
required more than one chunk."
```

---

### Task 2: Lower the shared file-search chunk constant

`app/services/file_search_service._MANIFEST_PAYLOAD_CHUNK_SIZE` is imported by `app/services/criteria_vector_service._string_list_metadata`, which runs on every criteria upload (`original_title_b64`, `created_at`). Today the value happens to fit in one chunk for typical titles, but the same 256-char ceiling applies, so this is a latent bug that should move in lockstep with Task 1.

**Files:**
- Modify: `app/services/file_search_service.py:22`
- Test: `tests/test_criteria_vector_service_chunk_limit.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_criteria_vector_service_chunk_limit.py`:

```python
"""criteria_vector_service._string_list_metadata respects File Search 256-char limit (issue #60)."""
from app.services.criteria_vector_service import _string_list_metadata


def test_string_list_metadata_chunks_under_256_chars():
    """Multi-chunk string_list_value entries must each be <= 256 chars."""
    # Title large enough to force multi-chunk after base64.
    long_value = "A" * 5000
    meta = _string_list_metadata("original_title_b64", long_value)

    values = meta["string_list_value"]["values"]
    assert len(values) > 1, "test setup must force multi-chunk output"
    longest = max(len(v) for v in values)
    assert longest <= 256, (
        f"chunk length {longest} exceeds Google File Search "
        f"string_list_value 256-char limit"
    )
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run: `pytest tests/test_criteria_vector_service_chunk_limit.py -v`
Expected: FAIL with `AssertionError: chunk length 3000 exceeds Google File Search string_list_value 256-char limit`

- [ ] **Step 3: Lower the file_search_service constant**

In `app/services/file_search_service.py`, change line 22:

```python
# Google File Search caps each string_list_value entry at 256 chars (issue #60).
# Keep in sync with alias_map_codec._CHUNK_SIZE.
_MANIFEST_PAYLOAD_CHUNK_SIZE = 240
```

- [ ] **Step 4: Run the new test and confirm it passes**

Run: `pytest tests/test_criteria_vector_service_chunk_limit.py -v`
Expected: PASS

- [ ] **Step 5: Run the related test suites to confirm no collateral damage**

Run: `pytest tests/test_criteria_vector_service_upload_metadata.py tests/services/test_file_search_manifest_document.py -v`
Expected: PASS (all tests). These suites exercise the live `upload_criteria` and the dead-but-tested `replace_single_document` paths; values they send are short enough to still produce a single chunk.

- [ ] **Step 6: Commit**

```bash
git add app/services/file_search_service.py tests/test_criteria_vector_service_chunk_limit.py
git commit -m "fix(criteria-meta): cap file-search chunk constant at 240 chars (issue #60)

_MANIFEST_PAYLOAD_CHUNK_SIZE is shared with the live
criteria_vector_service._string_list_metadata path, so it must obey the
same 256-char string_list_value ceiling that the alias_map codec now
respects."
```

---

### Task 3: Make SDK upload mocks enforce the real 256-char API constraint

The replace tests use plain `MagicMock(return_value=...)` for `upload_to_file_search_store`, so a future regression to >256-char chunks would silently pass mocked tests while breaking against the real API. This task adds one helper that mirrors the real server behaviour and rewires the existing replace tests to use it, so a chunk-size regression now trips the existing test suite.

**Files:**
- Modify: `tests/test_criteria_alias_map_service_replace.py`

- [ ] **Step 1: Add the imports and the enforcing-upload helper**

Add the `genai_errors` import alongside the existing third-party imports at the top of `tests/test_criteria_alias_map_service_replace.py`:

```python
from google.genai import errors as genai_errors
```

Then add the helper function immediately below the existing `_store()` helper:

```python
def _enforcing_upload(document_name):
    """Mimic Google File Search's 256-char string_list_value limit (issue #60)."""
    def fake_upload(**kwargs):
        config = kwargs.get("config") or {}
        for entry in config.get("custom_metadata") or []:
            sl = entry.get("string_list_value") or {}
            for value in sl.get("values") or []:
                if len(value) > 256:
                    raise genai_errors.ClientError(
                        400,
                        {"error": {
                            "code": 400,
                            "status": "INVALID_ARGUMENT",
                            "message": (
                                "* UploadToFileSearchStoreRequest."
                                "custom_metadata[1].string_list_value."
                                "values[0]: StringList value cannot be "
                                "more than 256 characters long.\n"
                            ),
                        }},
                    )
        op = MagicMock(done=True)
        op.response.document_name = document_name
        return op

    return fake_upload
```

- [ ] **Step 2: Rewire `test_replace_uploads_then_deletes_old`**

Replace the four lines that build and assign `upload_op`:

```python
    upload_op = MagicMock(done=True)
    upload_op.response.document_name = "docs/alias-map-new"
    client.file_search_stores.upload_to_file_search_store.return_value = upload_op
    client.file_search_stores.documents.delete = MagicMock()
```

with this:

```python
    client.file_search_stores.upload_to_file_search_store.side_effect = (
        _enforcing_upload("docs/alias-map-new")
    )
    client.file_search_stores.documents.delete = MagicMock()
```

- [ ] **Step 3: Rewire `test_replace_does_not_delete_when_no_old_doc`**

Replace the three lines that build and assign `upload_op`:

```python
    upload_op = MagicMock(done=True)
    upload_op.response.document_name = "docs/alias-map-1"
    client.file_search_stores.upload_to_file_search_store.return_value = upload_op
```

with this:

```python
    client.file_search_stores.upload_to_file_search_store.side_effect = (
        _enforcing_upload("docs/alias-map-1")
    )
```

(Leave `test_replace_does_not_delete_when_upload_fails` untouched — it already uses `side_effect` and is testing failure semantics independent of this helper.)

- [ ] **Step 4: Run the replace test module and confirm all three tests still pass**

Run: `pytest tests/test_criteria_alias_map_service_replace.py -v`
Expected: PASS (all 3 tests). The alias maps these tests build are tiny (zero or one entry), so encoded chunks are well under 256 chars and the enforcing fake never raises.

- [ ] **Step 5: Prove the strengthened mocks catch the original bug**

Temporarily revert `app/services/alias_map_codec.py:16` to `_CHUNK_SIZE = 3000`.

Run: `pytest tests/test_criteria_alias_map_service_replace.py -v`
Expected: still PASS — the alias_maps used in these tests are too small to produce a >256-char chunk even at the bug-era chunk size. That is fine: the next task (the reconcile regression test) is what produces a multi-chunk payload and exercises the enforcing fake. Restore `_CHUNK_SIZE = 240` before continuing.

- [ ] **Step 6: Commit**

```bash
git add tests/test_criteria_alias_map_service_replace.py
git commit -m "test(criteria-meta): enforce 256-char API limit in replace mocks (issue #60)

Adds an upload fake that mirrors Google File Search's real 400 response
when any custom_metadata string_list_value entry exceeds 256 chars, and
rewires the two happy-path replace tests to use it. Future regressions
that produce oversized chunks now fail at the SDK boundary instead of
silently passing through MagicMock."
```

---

### Task 4: Reconcile regression test for the legacy-surrogate code path

The production failure happened during the reconcile flow with two pre-v2 documents that received synthesized legacy-surrogate entries. The unit-level fixes above do not by themselves prove that reconcile now reaches the local-DB rebuild step instead of bailing out before `criteria_repo.insert(...)`. This task adds the missing regression test against the existing mock helpers in `tests/test_criteria_reconciliation_v2.py`, with one twist: `fake_alias.replace` is wired to enforce the 256-char API limit so the test would fail again if the chunk-size constant ever regresses.

**Files:**
- Modify: `tests/test_criteria_reconciliation_v2.py` (append one new test; add at most one import)

- [ ] **Step 1: Read the existing reconcile test conventions**

Read `tests/test_criteria_reconciliation_v2.py` end-to-end (it is short). Note in particular `_doc_kv(...)` for building criteria-doc fixtures, and `_reconcile_with_cloud_docs(...)` for running reconcile against mocked services. The new test reuses both rather than introducing real-DB plumbing.

- [ ] **Step 2: Add the `google.genai.errors` import**

At the top of `tests/test_criteria_reconciliation_v2.py`, add this import to the existing `import pytest` block area (place it grouped with the other third-party imports):

```python
from google.genai import errors as genai_errors
```

- [ ] **Step 3: Write the failing regression test**

Append the following test to `tests/test_criteria_reconciliation_v2.py` (do not modify existing tests):

```python
@pytest.mark.asyncio
async def test_reconcile_completes_dbcache_after_chunk_size_fix(monkeypatch):
    """Issue #60: pre-v2 docs force a multi-chunk alias_map upload. Before the
    fix, the upload failed with 400 INVALID_ARGUMENT (StringList > 256 chars)
    and reconcile bailed out before populating the local criteria cache, so
    the admin UI showed no criteria. After the fix, reconcile must reach the
    insert step and the alias_map service must receive entries for every
    pre-v2 doc.
    """
    docs = [
        _doc_kv(
            "fileSearchStores/rs/docs/pdf-xdo2amdu4xih",
            [("type", "criteria")],
        ),
        _doc_kv(
            "fileSearchStores/rs/docs/2022pdf-pbdczm0207y6",
            [("type", "criteria")],
        ),
    ]

    # Wrap _reconcile_with_cloud_docs's fake_alias.replace with a side_effect
    # that mirrors the real 256-char API limit. We monkeypatch the AliasMap
    # codec's chunker so the test fails if the chunk-size constant regresses.
    from app.services import alias_map_codec

    def _enforcing_replace(alias_map, old_doc_name=None):
        chunks = alias_map_codec.encode_alias_map_payload(
            alias_map.model_dump(mode="json")
        )
        longest = max((len(c) for c in chunks), default=0)
        if longest > 256:
            raise genai_errors.ClientError(
                400,
                {"error": {
                    "code": 400,
                    "status": "INVALID_ARGUMENT",
                    "message": (
                        "* UploadToFileSearchStoreRequest."
                        "custom_metadata[1].string_list_value.values[0]: "
                        "StringList value cannot be more than 256 characters "
                        "long."
                    ),
                }},
            )
        return "fileSearchStores/rs/docs/alias-map-new"

    # Patch the helper's AsyncMock replace before invoking the harness.
    # _reconcile_with_cloud_docs builds fresh mocks each call, so we patch
    # AsyncMock's call path at construction time by monkeypatching the
    # service class instead — the cleanest way is to drive reconcile
    # ourselves with the existing fakes plus our enforcing replace.
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.schemas.alias_map import AliasMap
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )

    fake_client = MagicMock()
    fake_vec = MagicMock()
    fake_vec.file_search_service.client = fake_client
    fake_vec.list_criteria_documents = AsyncMock(return_value=docs)

    fake_alias = MagicMock()
    # Start from no existing alias_map so reconcile synthesises both entries.
    fake_alias.fetch = AsyncMock(return_value=None)
    fake_alias.replace = AsyncMock(side_effect=_enforcing_replace)

    inserted = []
    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()

    async def _insert(**kwargs):
        inserted.append(kwargs)

    fake_repo.insert = _insert

    state_values = {"criteria_sync_state": "needs_resync"}
    fake_state = MagicMock()
    fake_state.get = AsyncMock(side_effect=lambda key: state_values.get(key))
    fake_state.set_many = AsyncMock(side_effect=state_values.update)
    fake_state.set = AsyncMock()

    db = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
        return_value="newhash",
    ):
        svc = CriteriaReconciliationService(
            db=db,
            vector_service=fake_vec,
            alias_map_service=fake_alias,
            criteria_repo=fake_repo,
            app_state_repo=fake_state,
        )
        result = await svc.reconcile()

    # Reconcile completed successfully.
    assert result.ok is True, f"reconcile failed: error={result.error}"
    assert result.error is None
    assert result.count == 2

    # alias_map.replace was called with one entry per pre-v2 doc.
    fake_alias.replace.assert_awaited_once()
    sent_alias_map: AliasMap = fake_alias.replace.await_args.args[0]
    assert len(sent_alias_map.entries) == 2

    # Local cache was rebuilt — both legacy-surrogate stable_ids inserted.
    assert len(inserted) == 2
    surrogate_ids = sorted(row["stable_id"] for row in inserted)
    assert all(sid.startswith("legacy_") for sid in surrogate_ids), surrogate_ids

    # Sync state was advanced to ok (not stuck on needs_resync).
    assert state_values.get("criteria_sync_state") == "ok"
```

- [ ] **Step 4: Run the new test and confirm it passes**

Run: `pytest tests/test_criteria_reconciliation_v2.py::test_reconcile_completes_dbcache_after_chunk_size_fix -v`
Expected: PASS. The chunk-size fix from Tasks 1–2 keeps every encoded chunk ≤256 chars, the enforcing fake does not raise, and reconcile reaches the insert step.

- [ ] **Step 5: Re-prove regression detection**

Temporarily revert `app/services/alias_map_codec.py:16` to `_CHUNK_SIZE = 3000`.

Run: `pytest tests/test_criteria_reconciliation_v2.py::test_reconcile_completes_dbcache_after_chunk_size_fix -v`
Expected: FAIL — the enforcing fake raises `ClientError(400)`, reconcile catches the exception and returns `ReconcileResult(error=...)`, so the `assert result.ok is True` assertion trips.

Restore the constant: edit `app/services/alias_map_codec.py:16` back to `_CHUNK_SIZE = 240`. Re-run the test to confirm it passes again.

- [ ] **Step 6: Commit**

```bash
git add tests/test_criteria_reconciliation_v2.py
git commit -m "test(criteria-meta): reconcile end-to-end with legacy surrogates (issue #60)

Adds the regression test that would have caught issue #60: two pre-v2
documents force a multi-chunk alias_map payload; the enforcing
alias-map fake raises 400 if any chunk exceeds 256 chars; reconcile
must still return ok=True and rebuild the local criteria cache."
```

---

### Task 5: Full-suite verification and final sanity check

**Files:** (no edits)

- [ ] **Step 1: Run the full criteria-meta-related test surface**

Run:
```bash
pytest tests/test_alias_map_codec.py \
       tests/test_criteria_alias_map_service_replace.py \
       tests/test_criteria_alias_map_service_fetch.py \
       tests/test_criteria_reconciliation_v2.py \
       tests/test_criteria_vector_service_upload_metadata.py \
       tests/test_criteria_vector_service_chunk_limit.py \
       tests/services/test_file_search_manifest_document.py \
       -v
```
Expected: PASS (every test).

- [ ] **Step 2: Run the entire test suite to confirm nothing else regressed**

Run: `pytest -q`
Expected: PASS. If any unrelated tests fail, do NOT patch them in this PR — confirm they were already failing on `main` (`git stash && pytest <failing test>::<failing case> -v && git stash pop`). Surface any pre-existing failures in the PR description.

- [ ] **Step 3: Verify the constants are in sync, per the in-code comment**

Run: `grep -n "240\|3000" app/services/alias_map_codec.py app/services/file_search_service.py`
Expected output contains both:
```
app/services/alias_map_codec.py:..:_CHUNK_SIZE = 240
app/services/file_search_service.py:22:_MANIFEST_PAYLOAD_CHUNK_SIZE = 240
```
And no `= 3000` lines.

- [ ] **Step 4: Optional manual smoke (only if the user has access to a live API key)**

Skip if running in CI or without a live key. Otherwise:

1. Start the app: `uvicorn app.main:app --reload`
2. Log in as admin and open the criteria list page.
3. Confirm: the two pre-v2 documents now appear in the list with a `legacy_*` stable_id and warnings in the server logs (warnings remain by design — the user must delete and re-upload to obtain v2 metadata before they can be used for evaluation).
4. Confirm: no 400 INVALID_ARGUMENT entries appear in the new reconcile logs.

- [ ] **Step 5: Open the PR referencing issue #60**

```bash
gh pr create \
  --title "fix(criteria-meta): cap File Search string_list_value chunks at 240 chars (closes #60)" \
  --body "$(cat <<'EOF'
## Summary
- Closes #60 (alias_map upload fails with `400 INVALID_ARGUMENT (StringList value > 256 chars)`, blocking the local criteria cache from being populated and hiding all criteria from the admin UI).
- Lowers `alias_map_codec._CHUNK_SIZE` and the in-sync `file_search_service._MANIFEST_PAYLOAD_CHUNK_SIZE` from 3000 → 240.
- Adds three layers of regression coverage so this cannot silently regress again:
  - codec-level chunk-bound test (≤256)
  - `_string_list_metadata` chunk-bound test (≤256)
  - SDK upload mock that mirrors the real 400 response when any chunk exceeds 256 chars (rewires both happy-path replace tests)
  - reconcile integration test that exercises the full legacy-surrogate path against the enforcing fake

## Test plan
- [x] `pytest tests/test_alias_map_codec.py`
- [x] `pytest tests/test_criteria_alias_map_service_replace.py`
- [x] `pytest tests/test_criteria_alias_map_service_fetch.py`
- [x] `pytest tests/test_criteria_reconciliation_v2.py`
- [x] `pytest tests/test_criteria_vector_service_chunk_limit.py`
- [x] `pytest tests/services/test_file_search_manifest_document.py`
- [x] `pytest -q` (full suite)
- [ ] (optional) Manual: start app with a key that has pre-v2 criteria docs; confirm reconcile no longer 400s and the legacy entries show up in the admin list.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
