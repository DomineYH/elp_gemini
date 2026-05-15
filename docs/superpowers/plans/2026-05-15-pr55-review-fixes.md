# PR 55 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining PR #55 review findings around upload dedup ordering, DB uniqueness, dashboard upload safety, and lint readiness.

**Architecture:** Keep the existing upload-event dedup design. Add focused regression coverage for the review findings, then make the smallest behavior and cleanup changes needed for current code to pass targeted tests and lint.

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite, pytest, pytest-asyncio, Ruff.

---

### Task 1: Confirm Current Review-Fix State

**Files:**
- Read: `app/services/lessonplan_analysis_service.py`
- Read: `app/migrations/lessonplan_uploads_table.py`
- Read: `app/models/analysis_reports.py`
- Read: `app/routers/views.py`

- [ ] **Step 1: Verify latest upload ordering code**

Check that `_find_existing_report_for_latest_upload()` orders by both timestamp and ID:

```python
.order_by(
    LessonPlanUpload.created_at.desc(),
    LessonPlanUpload.id.desc(),
)
```

- [ ] **Step 2: Verify DB uniqueness exists for fresh DBs**

Check that `AnalysisReport.__table_args__` defines the partial unique index:

```python
Index(
    "uq_analysis_reports_upload_id",
    "upload_id",
    unique=True,
    sqlite_where=text("upload_id IS NOT NULL"),
)
```

- [ ] **Step 3: Verify dashboard upload is streamed**

Check that `/dashboard/upload` reads chunks instead of `await file.read()`:

```python
chunk = await file.read(1024 * 1024)
```

### Task 2: Add Dashboard Upload Size Regression Test

**Files:**
- Modify: `tests/test_dashboard_upload_creates_upload_row.py`
- Modify: `app/routers/views.py`

- [ ] **Step 1: Write the failing test**

Add a test that monkeypatches the dashboard upload limit to a tiny value, posts a larger PDF, and asserts a 400 response with no `LessonPlanUpload` row:

```python
@pytest.mark.asyncio
async def test_dashboard_upload_rejects_file_over_limit(client, monkeypatch):
    c, session_factory = client

    from app.routers import views as views_mod

    monkeypatch.setattr(views_mod, "DASHBOARD_MAX_UPLOAD_SIZE", 8)
    files = {
        "file": (
            "plan.pdf",
            BytesIO(b"%PDF-1.4\nlarger-than-limit"),
            "application/pdf",
        )
    }

    with patch("app.routers.views.PdfReader") as mock_reader:
        res = await c.post("/dashboard/upload", files=files)

    assert res.status_code == 400
    assert "파일 크기는" in res.text
    mock_reader.assert_not_called()

    async with session_factory() as s:
        rows = (
            await s.execute(select(LessonPlanUpload))
        ).scalars().all()
        assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=. SECRET_KEY=abcdefghijklmnopqrstuvwxyz123456 GOOGLE_API_KEY=dummy RATE_LIMIT_ENABLED=false uv run --extra dev pytest tests/test_dashboard_upload_creates_upload_row.py::test_dashboard_upload_rejects_file_over_limit -q
```

Expected: FAIL because `DASHBOARD_MAX_UPLOAD_SIZE` is missing or the endpoint accepts the upload.

- [ ] **Step 3: Implement streaming size limit**

In `app/routers/views.py`, add a module-level limit based on `FileValidator.MAX_FILE_SIZE` and reject oversized uploads before PDF parsing/File Search/DB insert:

```python
DASHBOARD_UPLOAD_CHUNK_SIZE = 1024 * 1024
DASHBOARD_MAX_UPLOAD_SIZE = FileValidator.MAX_FILE_SIZE
```

```python
total_size = 0
too_large = False
with open(file_path, "wb") as buffer:
    while True:
        chunk = await file.read(DASHBOARD_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > DASHBOARD_MAX_UPLOAD_SIZE:
            too_large = True
            break
        buffer.write(chunk)
        hasher.update(chunk)
if too_large:
    file_path.unlink(missing_ok=True)
    return templates.TemplateResponse(..., status_code=400)
```

- [ ] **Step 4: Run test to verify it passes**

Run the same targeted test. Expected: PASS.

### Task 3: Clean Changed-File Lint Failures

**Files:**
- Modify: `app/models/analysis_reports.py`
- Modify: `app/routers/views.py`
- Modify: `app/services/lessonplan_analysis_service.py`
- Modify: `tests/services/test_lessonplan_analysis_service_dedup.py`
- Modify: `tests/test_dashboard_upload_creates_upload_row.py`
- Modify: `tests/test_lessonplan_uploads_model.py`

- [ ] **Step 1: Run targeted Ruff to capture current failures**

```bash
PYTHONPATH=. SECRET_KEY=abcdefghijklmnopqrstuvwxyz123456 GOOGLE_API_KEY=dummy RATE_LIMIT_ENABLED=false uv run --extra dev ruff check app/main.py app/migrations/lessonplan_uploads_table.py app/models/analysis_reports.py app/services/lessonplan_analysis_service.py app/routers/views.py tests/test_lessonplan_uploads_model.py tests/services/test_lessonplan_analysis_service_dedup.py tests/test_dashboard_upload_creates_upload_row.py
```

Expected before cleanup: import ordering, unused imports, naming, and line-length failures.

- [ ] **Step 2: Apply mechanical import cleanup**

Run Ruff fix on the same targeted files:

```bash
PYTHONPATH=. SECRET_KEY=abcdefghijklmnopqrstuvwxyz123456 GOOGLE_API_KEY=dummy RATE_LIMIT_ENABLED=false uv run --extra dev ruff check --fix app/main.py app/migrations/lessonplan_uploads_table.py app/models/analysis_reports.py app/services/lessonplan_analysis_service.py app/routers/views.py tests/test_lessonplan_uploads_model.py tests/services/test_lessonplan_analysis_service_dedup.py tests/test_dashboard_upload_creates_upload_row.py
```

- [ ] **Step 3: Manually wrap remaining long lines**

Wrap only the targeted files' remaining `E501` lines without changing behavior.

- [ ] **Step 4: Re-run targeted Ruff**

Run the targeted Ruff command again. Expected: no errors.

### Task 4: Final Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run PR #55 relevant tests**

```bash
PYTHONPATH=. SECRET_KEY=abcdefghijklmnopqrstuvwxyz123456 GOOGLE_API_KEY=dummy RATE_LIMIT_ENABLED=false uv run --extra dev pytest tests/test_lessonplan_uploads_model.py tests/services/test_lessonplan_storage_service.py tests/test_lessonplan_upload_router.py tests/services/test_lessonplan_analysis_service_dedup.py tests/test_lessonplan_analysis_router_429.py tests/test_dashboard_upload_creates_upload_row.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Re-run targeted Ruff**

Run the targeted Ruff command from Task 3. Expected: no errors.

- [ ] **Step 3: Inspect git diff**

```bash
git diff --stat
git diff -- app/routers/views.py tests/test_dashboard_upload_creates_upload_row.py
```

Expected: changes are limited to the review fixes, lint cleanup, and this plan.
