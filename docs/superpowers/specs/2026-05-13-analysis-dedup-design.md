# Lesson Plan Analysis Deduplication — Design Spec

**Date:** 2026-05-13
**Status:** Approved (brainstorming → ready for plan)
**Supersedes:** `docs/plans/2026-05-13-fix-503-unavailable-retry.md` (to be deleted) and GitHub issue [#53](https://github.com/DomineYH/elp_gemini/issues/53) (to be closed)

## Problem

When a user uploads a lesson plan and clicks [분석하기], the first analysis succeeds. Clicking [분석하기] again on the same upload re-invokes Gemini unnecessarily — burning quota, occasionally surfacing transient 503 UNAVAILABLE as a hard error to the user, and producing a second `AnalysisReport` row that duplicates the first.

The earlier fix attempt (`docs/plans/2026-05-13-fix-503-unavailable-retry.md`) treated the symptom — making the retry helper recover from transient 5xx errors. The root issue is that **the system shouldn't call Gemini again for an upload that's already been analyzed.**

## Goal

Define an **upload event** as the unit of analysis. One upload event maps to at most one analysis report. Re-clicking [분석하기] on the same upload must:

1. Not call Gemini.
2. Return HTTP 409 with the existing report's id.
3. On the frontend, surface "이미 분석된 문서입니다." and auto-open the existing report.

Re-analysis is enabled by **uploading again** — even the same file. Every upload action creates a new event.

## Architecture

Add a `lessonplan_uploads` table that records one row per upload action. Add `analysis_reports.upload_id` (FK, UNIQUE, nullable) to express the 1:1 mapping. Dedup is enforced authoritatively in the backend service via a pre-flight check, with the DB UNIQUE constraint serving as the race-condition safety net.

Existing 429 RESOURCE_EXHAUSTED retry logic from PR #52 (`app/utils/gemini_retry.py`, `app/services/lessonplan_analysis_service.py:27`) is preserved unchanged — it's already operational. No new 5xx retry logic is introduced; dedup eliminates the primary path to that failure mode.

## Components

### 1. New table — `lessonplan_uploads`

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `id` | `INTEGER` | PK, autoincrement | Surrogate key |
| `user_id` | `INTEGER` | FK → `users.id`, NOT NULL, indexed | Owner |
| `filename` | `VARCHAR(500)` | NOT NULL | Server-side name (`{username}_{original}`) |
| `original_filename` | `VARCHAR(500)` | NULL | User-uploaded name |
| `file_hash` | `VARCHAR(64)` | NULL | SHA-256 of bytes — column reserved for future content-dedup; **not** used by this design's check |
| `created_at` | `DATETIME` | NOT NULL, `server_default=now()`, indexed | Event time |

### 2. Modified table — `analysis_reports`

Add:

- `upload_id INTEGER NULL REFERENCES lessonplan_uploads(id)`
- `UNIQUE (upload_id)` — DB-level guarantee of 1:1
- Index on `upload_id`

Existing rows stay `NULL` — no backfill. SQLite/Postgres treat multiple NULL values as distinct under UNIQUE, so legacy rows do not collide.

### 3. Modified service — `LessonPlanStorageService.save_lessonplan`

After writing the file to disk:

1. Compute SHA-256 of `file_content`.
2. INSERT a row into `lessonplan_uploads` (always a new row, even if the on-disk file was overwritten).
3. Return the new `upload_id` in the response dict alongside the existing fields.

The upload router persists `upload_id` somewhere the analyze flow can read it back — see "Upload-to-analyze handoff" below.

### 4. Modified service — `LessonPlanAnalysisService.analyze_lesson_plan`

Pre-flight before calling Gemini:

1. `latest_upload = SELECT … FROM lessonplan_uploads WHERE user_id = ME ORDER BY created_at DESC LIMIT 1`
   - If `latest_upload is None` → return existing "분석할 문서가 없습니다." error (no schema change to that branch).
2. `existing = SELECT … FROM analysis_reports WHERE upload_id = latest_upload.id`
   - If `existing is not None` → return `{success: False, error_code: "ALREADY_ANALYZED", error: "이미 분석된 문서입니다.", report_id: existing.id}`. **Skip Gemini call entirely.**
3. Otherwise: run the existing analyze flow (file search + generate_content + retries already wired up).
4. On successful analysis, INSERT `AnalysisReport` with `upload_id = latest_upload.id`. If the INSERT raises `sqlalchemy.exc.IntegrityError` on the `uq_analysis_reports_upload_id` constraint → re-fetch the conflicting row, return `ALREADY_ANALYZED` with its `report_id` (race-condition fallback).

### 5. Modified router — `app/routers/lessonplan_analysis.py`

Add a branch before the existing `RESOURCE_EXHAUSTED` / 500 branches:

```python
if result.get("error_code") == "ALREADY_ANALYZED":
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=result.get("error", "이미 분석된 문서입니다."),
        headers={"X-Report-Id": str(result["report_id"])},
    )
```

The `report_id` is exposed both in the `X-Report-Id` header and in the JSON body (`detail` field stays as the message; add `report_id` as a sibling). The frontend reads either.

Existing 429 branch and generic 500 branch stay verbatim.

### 6. Frontend — `app/templates/user/dashboard.html` analyze handler

In the existing `fetch('/api/lessonplan/analyze', …)` handler:

- After `await fetch`, branch on `response.status === 409`:
  - Parse JSON body for `report_id`.
  - Show toast: "이미 분석된 문서입니다."
  - Call the existing `GET /api/lessonplan/reports/{report_id}` flow and open the report viewer.
  - Return early (do NOT throw — this is not an error path for the user).
- All other branches (200 / 429 / 500) unchanged.

## Data Flow

### Scenario A: New upload → analyze (happy path)

```
POST /api/lessonplans/upload
  → save_lessonplan() writes file + INSERT lessonplan_uploads (id=42)
POST /api/lessonplan/analyze
  → latest_upload.id = 42
  → analysis_reports WHERE upload_id=42 → None
  → Gemini call (with PR #52's 429 retry)
  → INSERT analysis_reports (…, upload_id=42)
  → 200 OK + report JSON
```

### Scenario B: Re-click [분석하기] on same upload (blocked path)

```
POST /api/lessonplan/analyze   (no new upload)
  → latest_upload.id = 42 (unchanged)
  → analysis_reports WHERE upload_id=42 → row with id=17
  → return ALREADY_ANALYZED + report_id=17  (no Gemini call)
Router → HTTP 409 + {detail, report_id: 17}
Frontend → toast + auto-open viewer for report 17
```

### Scenario C: New upload (same or different file) → re-analyze (re-enabled)

```
POST /api/lessonplans/upload   (any file)
  → INSERT lessonplan_uploads (id=43)
POST /api/lessonplan/analyze
  → latest_upload.id = 43
  → analysis_reports WHERE upload_id=43 → None
  → normal flow, INSERT report with upload_id=43
```

## Upload-to-analyze handoff

`analyze_lesson_plan` currently has no upload_id input — it discovers files via `LessonPlanStorageService.list_lessonplans(username)` and picks the most recent by `created_at`. This design keeps that contract: the **latest row in `lessonplan_uploads`** for the user is the implicit input. The analyze API does not require a new request parameter.

Trade-off accepted: if a user uploads file A, then file B, then clicks [분석하기], only file B is analyzable. This matches the current behavior (latest-wins).

## Error Handling

| Condition | Service return | HTTP status | Notes |
|---|---|---|---|
| No upload yet | `{success: False, error: "분석할 문서가 없습니다…"}` | 500 (existing) | Unchanged from current code |
| Latest upload already has a report | `{success: False, error_code: "ALREADY_ANALYZED", report_id, error: "이미 분석된 문서입니다."}` | **409 Conflict** | New |
| Race condition — second INSERT hits UNIQUE | Catch `IntegrityError`, refetch existing row, same as above | 409 | New |
| Gemini 429 after retries | Existing `GeminiQuotaExhausted` → `error_code="RESOURCE_EXHAUSTED"` | 429 (existing) | Unchanged |
| Gemini 503 / other 5xx | Generic `except Exception` → `error: "분석 중 오류 발생"` | 500 (existing) | Unchanged. Dedup makes repeat-click recoveries unnecessary. |

## Testing

### Unit

| Test | File | Asserts |
|---|---|---|
| `test_save_lessonplan_inserts_upload_row` | `tests/services/test_lessonplan_storage_service.py` | After `save_lessonplan()`, exactly one new row in `lessonplan_uploads` with matching user/filename; return dict contains `upload_id` |
| `test_save_lessonplan_creates_new_row_on_resave` | (same) | Two consecutive `save_lessonplan` calls with same `original_filename` produce **two** distinct `lessonplan_uploads` rows |
| `test_analyze_blocks_when_upload_already_analyzed` | `tests/services/test_lessonplan_analysis_service.py` | Pre-seeded `AnalysisReport.upload_id = N` → `analyze_lesson_plan` returns `error_code="ALREADY_ANALYZED"`, `report_id=N`; Gemini client mock has 0 calls |
| `test_analyze_proceeds_when_new_upload` | (same) | Fresh upload row, no matching report → Gemini mock called once, new `AnalysisReport` row inserted with `upload_id` set |
| `test_analyze_race_fallback` | (same) | Pre-seed an upload, mock Gemini success, mock DB INSERT to raise `IntegrityError` on `uq_analysis_reports_upload_id` → service returns `ALREADY_ANALYZED` with the conflicting row's id (no exception bubbles) |

### Router integration

Add to existing `tests/test_lessonplan_analysis_router_retry.py`:

| Test | Asserts |
|---|---|
| `test_analyze_returns_409_on_already_analyzed` | Service mock returns `error_code="ALREADY_ANALYZED", report_id=17` → response 409, body `detail == "이미 분석된 문서입니다."`, `report_id == 17`, header `X-Report-Id == "17"` |
| Existing `test_analyze_returns_429_on_resource_exhausted` | Unchanged — regression guard |
| Existing `test_analyze_returns_500_on_generic_error` | Unchanged — regression guard |

### Manual (frontend)

1. Upload → 분석하기 → report renders ✓
2. 분석하기 again (no new upload) → toast "이미 분석된 문서입니다" + viewer auto-opens existing report ✓
3. Upload again (same name, same content) → 분석하기 → new analysis runs ✓
4. Force a Gemini failure on a fresh upload (e.g. invalid API key) → 분석하기 again still triggers Gemini (no `AnalysisReport` row exists yet) ✓

## Migration

Single Alembic revision: `add_lessonplan_uploads_and_upload_id`.

```python
def upgrade():
    op.create_table(
        "lessonplan_uploads",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.func.now(), index=True),
    )
    op.add_column(
        "analysis_reports",
        sa.Column("upload_id", sa.Integer,
                  sa.ForeignKey("lessonplan_uploads.id"), nullable=True),
    )
    op.create_unique_constraint(
        "uq_analysis_reports_upload_id",
        "analysis_reports", ["upload_id"],
    )
    op.create_index(
        "ix_analysis_reports_upload_id",
        "analysis_reports", ["upload_id"],
    )

def downgrade():
    op.drop_index("ix_analysis_reports_upload_id", table_name="analysis_reports")
    op.drop_constraint("uq_analysis_reports_upload_id",
                       "analysis_reports", type_="unique")
    op.drop_column("analysis_reports", "upload_id")
    op.drop_table("lessonplan_uploads")
```

NULL handling: SQLite (current DB) and PostgreSQL both treat multiple NULL values as distinct under UNIQUE, so legacy `analysis_reports` rows with `upload_id IS NULL` do not collide.

Rollback: `alembic downgrade -1` followed by reverting the application commits. The `upload_id` column is nullable, so a partial rollback (DB reverted, code still present) does not crash on writes — service code defensively treats `latest_upload is None` as "no upload yet" and the existing 500 branch fires.

## Acceptance Criteria

- [ ] New upload + [분석하기] once → analysis succeeds end-to-end and the new `AnalysisReport` row has `upload_id` set.
- [ ] Re-click [분석하기] on the same upload → HTTP 409 + `X-Report-Id` header + JSON `report_id`; server log shows **zero** new Gemini calls.
- [ ] Frontend on 409 → "이미 분석된 문서입니다" toast + viewer auto-opens the report identified by `report_id`.
- [ ] After uploading any file again → [분석하기] runs normally (analysis re-enabled).
- [ ] Two concurrent [분석하기] clicks on the same upload → both end as HTTP 409 (no 500 from un-caught `IntegrityError`).
- [ ] PR #52's 429 retry behavior preserved (regression test stays green).
- [ ] `uv run pytest tests/ -x` passes.

## Out of Scope

- **Content-hash dedup across uploads.** `file_hash` is recorded for future use; this design does not branch on it.
- **Backfill of pre-existing `AnalysisReport` rows.** They stay `upload_id IS NULL`. Users get the new behavior on their next upload.
- **Cross-user dedup / report sharing.**
- **Gemini 503 retry.** The previous 503 plan is superseded by this design and will be deleted as part of implementation.
- **Hashing offload.** SHA-256 happens synchronously in `save_lessonplan` on the bytes already in memory — no streaming, no thread pool.

## Open Questions

None — all design points settled during brainstorming on 2026-05-13.

## Implementation Notes (for the plan)

When the writing-plans skill picks this up, the natural task split is:

1. Alembic migration + SQLAlchemy model for `lessonplan_uploads` + `AnalysisReport.upload_id`
2. `LessonPlanStorageService.save_lessonplan` — INSERT row + return upload_id (TDD with unit tests)
3. `LessonPlanAnalysisService.analyze_lesson_plan` — pre-flight check + race-condition fallback (TDD)
4. Router — 409 branch + tests
5. Frontend — 409 handler in dashboard.html (manual verify)
6. Cleanup — delete `docs/plans/2026-05-13-fix-503-unavailable-retry.md`, close issue #53 with a link to the new issue
