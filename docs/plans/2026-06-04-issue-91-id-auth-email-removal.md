# Issue #91 — id 로그인·email 제거 영향요소 정리 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use agent-team-driven-development to execute this plan.
> Execution governance follows `team_agents.md`: Opus = team lead (plan/assign/manage/consolidate), Sonnet = specialist coders. Each specialist works in its **own git worktree**; the lead merges each wave into the integration branch and resolves conflicts.

**Goal:** Complete the post-#90 cleanup (issue #91, §0–§7): re-key all per-user file/vector storage to the immutable `User.id`, remove `role`/`region`/`career` (`UserProfile`) and `email` from the entire system (DB, admin, export, templates, docs, tests).

**Architecture:** A FastAPI + SQLAlchemy(async, SQLite) RAG platform. #90 already switched login from email → user-chosen id and removed role/region/career from the registration form, but the *data model, admin, export, storage keys, templates, docs, and tests* still carry the old email/profile concepts. This plan finishes that removal. Storage ownership moves from fragile `f"{username}_"` flat-prefix matching to **per-user subdirectories keyed by `User.id`** (exact boundary, no sanitization collisions). `UserProfile` table and `User.email` column are physically dropped via startup migrations.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), SQLite, Jinja2 templates + vanilla JS, Google GenAI File Search, pytest (`asyncio_mode=auto`).

**Confirmed decisions (from product owner):**
1. Scope = **all of §0–§7** in this single PR.
2. §0 existing on-disk files / Gemini stores keyed by old username = **forward-only; abandon existing** (no data migration; dev/test stage).
3. §5 = **fully remove** `User.email` column **and** the legacy email-login fallback paths.
4. §3 `chat_sessions.user_type` = **keep the column**; new sessions record `"미지정"`; legacy session labels & admin QnA filter preserved.

**Baseline (must hold before & after):** `python -m pytest` has **23 pre-existing collection errors** (`No module named 'app.models.documents'` etc.) — unrelated, do **not** fix. The files this plan touches currently pass: run
`.venv/bin/python -m pytest tests/test_user_id_password_auth.py tests/test_admin_users.py tests/test_admin_export_service.py tests/unit/test_admin_export_naming.py tests/unit/test_admin_export_filters.py tests/test_auth_middleware_whitelist.py -q`
→ **145 passed**. Use `.venv/bin/python -m pytest` (bare `python` is absent; bare `pytest` can't import `app`).

---

## Wave Analysis

### Specialists

| Role | Expertise | Tasks |
|------|-----------|-------|
| backend-engineer | Python, FastAPI routers, SQLAlchemy async, SQLite migrations, pytest, Google File Search service | Tasks 1, 2, 3, 4 |
| frontend-engineer | Jinja2 templates, embedded vanilla JS, admin dashboard UI | Task 5 |
| docs-engineer | Markdown specs/docs, OpenAPI YAML, helper scripts | Task 6 |

### Waves

**Wave 1: Decoupling foundations** — re-key storage and strip `UserProfile`/`email` *consumption* from the two independent consumer subsystems, so Wave 2 can safely drop the table/column. These three tasks touch fully disjoint file sets.
- Task 1 (backend-engineer) — §0 re-key all per-user file & vector storage to `User.id` (per-user subdirs); delete collision-skip logic.
- Task 2 (backend-engineer) — §1 admin router/schemas: drop `UserProfile`/`email` reads; password-reset gate by id-login-capability.
- Task 3 (backend-engineer) — §2 export: drop role/region/career/email filters, naming tokens, CSV columns; read new storage layout.

  *Parallel-safe because:* Task 1 owns `app/services/{lessonplan_storage,analysis_storage,report_storage,lessonplan_vector,file_search,admin_deletion,eval_service,lessonplan_analysis_service}.py` + `app/routers/{views,evaluations,lessonplan_analysis}.py` + the storage/logout/store-id lines of `app/routers/auth.py` & `app/routers/qna.py`. Task 2 owns `app/routers/admin/users.py` + `app/schemas/admin.py`. Task 3 owns `app/services/admin_export_service.py` + `app/utils/admin_export_naming.py` + `app/schemas/admin_export.py` + `app/routers/admin/exports.py` + the export-endpoint lines of `app/routers/admin/dashboard.py`. No file is shared; no import cycle among them.

**Wave 2: Drop the data model** — needs Wave 1 complete so that **no code references `UserProfile` or `User.email`** any longer (except the model/auth files this wave owns).
- Task 4 (backend-engineer) — §3+§5 drop `UserProfile` table + remove `User.email` column (startup migrations), redefine session segment to `"미지정"`, purge dead constants, delete email-login fallback in auth, remove `email` from user schemas; rewrite auth/whitelist tests & conftest fixtures.
- Task 6 (docs-engineer) — §6 docs/specs/README/scripts: supersede contradicting plans, fix OpenAPI `/auth/login`, flag the destructive wipe script.

  *Parallel-safe because:* Task 4 is all Python/DB (`app/models/*`, `app/migrations/*`, `app/services/auth_service.py`, `app/schemas/users.py`, `app/constants.py`, `app/main.py`, login-path lines of `app/routers/auth.py`, segment lines of `app/routers/qna.py`, and tests). Task 6 is all Markdown/YAML/scripts under `docs/`, `specs/`, `README.md`, `scripts/`. Zero file overlap.
  *Depends on Wave 1:* Task 4 can only drop the `user_profiles` table and `users.email` column after Task 2 (admin) and Task 3 (export) have removed every `UserProfile`/`User.email` query/import. Task 4 also branches from Task 1's merged `auth.py`/`qna.py` edits (different lines, sequential — no conflict).

**Wave 3: User-facing surface** — needs Wave 1 (Task 2's admin JSON shape, Task 3's export-modal params) and Wave 2 (Task 4's removal of `user.email`).
- Task 5 (frontend-engineer) — §4 templates: remove `user.email` from nav, role/region/career columns+badges+filters from admin tables, role/region/career inputs from the export modal.

  *Parallel-safe because:* single task in the wave.
  *Depends on:* Task 2 (admin accounts/sessions/profile JSON no longer returns `email`/`profile`), Task 3 (export query params `role`/`region`/`career_min`/`career_max` removed), Task 4 (`user.email` no longer exists on the model).

**Consolidation (team lead, not a specialist task):** After Wave 3 merges, the lead runs the full target test suite **and** an app-startup smoke test (fresh SQLite → confirm both new migrations run and the table/column are gone), resolves any integration gaps, then opens the PR. (Per `team_agents.md`, consolidation is the lead's responsibility.)

### Dependency Graph

```
Task 1 (§0 storage) ─────────────┐
Task 2 (§1 admin)  ──┐           ├─→ Task 4 (§3+§5 model/auth) ──┐
Task 3 (§2 export) ──┴── needs 1 ┘           Task 6 (§6 docs) ───┴─→ Task 5 (§4 templates) ─→ [lead consolidation → PR]
                                              (6 has no deps; parked in Wave 2)
```
Acyclic. Task 3 depends on Task 1 (storage layout). Task 4 depends on Tasks 1+2+3. Task 5 depends on Tasks 2+3+4. Task 6 is independent (scheduled in Wave 2 to balance load).

---

## Tasks

### Task 1: §0 — Re-key per-user storage to `User.id`

**Specialist:** backend-engineer
**Depends on:** None
**Produces:** New on-disk layout = **per-user subdirectory by `User.id`** for every per-user store; Gemini store name = `f"user-{user_id}-store"`; File Search upload metadata `user_id = str(user.id)`; session carries `user_id`. Documented conventions consumed by Task 3 (export lessonplan collection) and Task 5 (upload URLs).

**The convention (all consumers must match):**
- Lesson plans: `data/lessonplan/{user_id}/{original_filename}`
- Analyses: `data/analys/{user_id}/{base_name}.md`
- Reports: `app/static/reports/{user_id}/{timestamp}_{base}_{unique8}_reports.md`
- Dashboard uploads: `app/static/uploads/{user_id}/{timestamp}_{safe_original}`
- Gemini File Search store: display name `f"user-{user_id}-store"` (integer → ASCII-safe, no sanitization collision)
- Ownership is now **implicit** (a caller can only reach its own `{user_id}/` subtree) → delete all `startswith(f"{username}_")`, `glob(f"{username}_*")`, and every collision-skip branch.

**Files:**
- Modify: `app/services/lessonplan_storage_service.py` — every method signature `username: str` → `user_id: int`; build paths as `self.base_dir / str(user_id) / ...`; `list_*` = iterate `self.base_dir / str(user_id)` (return `[]` if missing); `mkdir(parents=True)` the per-user dir on save.
- Modify: `app/services/analysis_storage_service.py` — same transformation (save/get/list/delete at lines 93/135/168/219).
- Modify: `app/services/report_storage_service.py` — same; replace `filename.startswith(f"{username}_")` ownership checks (lines ~108, ~176) with subdir containment (`(self.base_dir / str(user_id) / filename).resolve()` is inside the user dir).
- Modify: `app/services/lessonplan_vector_service.py` — `user_key` → `user_id`; store name `f"user-{user_id}-store"` (lines ~165, ~282); metadata `user_id` = `str(user_id)` (line ~50).
- Modify: `app/services/file_search_service.py` — `get_dual_store_ids` / `get_user_store_id` / `upload_document` build `f"user-{user_key}-store"` where `user_key` is now the int id (lines 245, 314, 379); update docstrings ("username" → "User.id").
- Modify: `app/services/admin_deletion_service.py` — replace `_delete_file_search_store` collision logic (263–297) with a single delete of `user-{user_id}-store`; replace lessonplan/static-upload prefix+collision loops (391–496) with `shutil.rmtree(dir / str(user_id), ignore_errors=True)`. Drop now-dead helpers (`_username_has_ascii_signature`, sanitize-collision checks) and the `other_usernames` parameter threading where it existed only for collision detection.
- Modify: `app/services/eval_service.py` — `save_analysis`/list/get/delete calls (127, 257, 274, 291) pass `user_id` instead of `username`.
- Modify: `app/services/lessonplan_analysis_service.py` — `analyze_lesson_plan`/`list_lessonplans`/`save_report`/`_user_file_search_store_has_documents`/`_get_store_ids` (116, 184, 187, 202, 368, 512) keyed by `user_id`.
- Modify: `app/routers/views.py` — upload/cleanup (129–132, 179, 184, 270): `safe_username` prefix removed; pass `current_user.id`; store name `f"user-{current_user.id}-store"`; metadata `user_id=str(current_user.id)`; uploaded-file URL now `/static/uploads/{id}/{name}`.
- Modify: `app/routers/evaluations.py` — pass `current_user.id` (61, 81, 136).
- Modify: `app/routers/lessonplan_analysis.py` — pass `current_user.id` (53, 111).
- Modify: `app/routers/auth.py` — **login**: also set `request.session["user_id"] = user.id` (next to existing `session["username"]`, ~line 93). **logout** (548–565): read `user_id = request.session.get("user_id")`; `store_name = f"user-{user_id}-store"`. (Touch only these lines; login-credential/email logic belongs to Task 4 and lands in a later wave.)
- Modify: `app/routers/qna.py` — the File-Search store-id lookup call only: pass `current_user.id`. (Do **not** touch `_session_segment_label_for_user` — that is Task 4.)
- Test: `tests/unit/test_lessonplan_storage_service.py` (exists), `tests/unit/test_admin_deletion_service*.py` if present; otherwise add `tests/unit/test_storage_user_id_keying.py`.

**Step 1: Write the failing test** (storage keying + isolation + deletion)

Add `tests/unit/test_storage_user_id_keying.py`:
```python
from pathlib import Path
from app.services.lessonplan_storage_service import LessonPlanStorageService

def test_lessonplan_saved_under_user_id_subdir(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    res = svc.save_lessonplan(user_id=42, original_filename="plan.pdf",
                              file_content=b"x")
    assert Path(res["file_path"]) == tmp_path / "42" / "plan.pdf"
    assert svc.list_lessonplans(user_id=42)[0]["original_filename"] == "plan.pdf"

def test_user_cannot_see_other_users_files(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    svc.save_lessonplan(user_id=1, original_filename="a.pdf", file_content=b"a")
    svc.save_lessonplan(user_id=12, original_filename="b.pdf", file_content=b"b")
    assert [p["original_filename"] for p in svc.list_lessonplans(user_id=1)] == ["a.pdf"]
    assert svc.list_lessonplans(user_id=12)[0]["original_filename"] == "b.pdf"
```

**Step 2: Run test to verify it fails**
Run: `.venv/bin/python -m pytest tests/unit/test_storage_user_id_keying.py -q`
Expected: FAIL (current signature takes `username`, files are flat-prefixed).

**Step 3: Write minimal implementation** — apply the subdir transformation to the storage services and all callers listed above.

**Step 4: Run tests to verify they pass**
Run: `.venv/bin/python -m pytest tests/unit/ -q -k "storage or deletion"`
Expected: PASS. Then run the full app-import smoke: `.venv/bin/python -c "import app.main"` → no error.

**Step 5: Commit**
```bash
git add app/services app/routers/views.py app/routers/evaluations.py app/routers/lessonplan_analysis.py app/routers/auth.py app/routers/qna.py tests/unit/test_storage_user_id_keying.py
git commit -m "refactor(storage): key per-user files & vector stores by User.id (#91 §0)"
```

---

### Task 2: §1 — Admin router/schemas drop `UserProfile`/`email`

**Specialist:** backend-engineer
**Depends on:** None
**Produces:** Admin user APIs (`/admin/api/users/...`) that contain **no** `email`, `profile`, `role`, `region`, `career` fields and gate password-reset on **id-login capability** rather than email. Consumed by Task 5 (admin templates) and Task 4 (which then drops the table/column safely).

**Files:**
- Modify: `app/routers/admin/users.py`
  - Delete the `UserProfile` import (line 33) and all UserProfile queries: `_serialize_profile` (82–152), `_load_profiles` (155–175), `_get_profile_totals` (178–222). Remove `profile`/`profile_role`/`profile_summary` from every response (`get_user_sessions` 450–451, `get_user_accounts` 551–553, `get_user_profile_for_admin` 832). Remove profile role counts from `get_user_stats` (361, 366–369) — keep only the non-profile totals.
  - `_user_identifier` (66–70): return `user.username` (drop email fallback).
  - `_user_can_login` (73–79): replace email check with `AuthService._has_valid_custom_id(user)` (id-based login capability). `can_change_password` (557–559) then follows.
  - Remove the email search filter (501–509) and the `email` response fields (441, 543, 827).
- Modify: `app/schemas/admin.py` — remove the dead `email`/`user_email` fields from `AdminUserResponse` (30), `AdminUserDetailResponse` (45), `AdminQALogResponse` (66). If a class becomes unused, leave it (out of scope) but note it.
- Test: `tests/test_admin_users.py` — update assertions: accounts/sessions/profile responses no longer carry `email`/`profile`; `can_change_password` is true for id-capable users; identifier == username.

**Step 1: Write the failing test** — adjust `tests/test_admin_users.py`:
```python
# accounts response no longer exposes email or profile
assert "email" not in body["accounts"][0]
assert "profile" not in body["accounts"][0]
assert body["accounts"][0]["user_identifier"] == body["accounts"][0]["username"]
# id-capable regular user can have password changed (no email needed)
assert body["accounts"][0]["can_change_password"] is True
```
(Remove/replace the existing `email is None` / `"profile" in ...` assertions.)

**Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_admin_users.py -q`
Expected: FAIL (responses still include `email`/`profile`).

**Step 3: Implement** the deletions/replacements above.

**Step 4: Verify pass**
Run: `.venv/bin/python -m pytest tests/test_admin_users.py -q`
Expected: PASS. Smoke: `.venv/bin/python -c "import app.routers.admin.users"`.

**Step 5: Commit**
```bash
git add app/routers/admin/users.py app/schemas/admin.py tests/test_admin_users.py
git commit -m "refactor(admin): drop UserProfile/email from user APIs; gate pw-reset by id (#91 §1)"
```

---

### Task 3: §2 — Export drop role/region/career/email

**Specialist:** backend-engineer
**Depends on:** Task 1 (lesson-plan on-disk layout is now `data/lessonplan/{user_id}/...`)
**Produces:** Export ZIP whose filters, filename tokens, and CSV columns no longer reference role/region/career/email; lessonplan collection reads the per-`user_id` subdir layout. Consumed by Task 5 (export modal template).

**Files:**
- Modify: `app/schemas/admin_export.py` — remove `role`/`region`/`career_min`/`career_max` from `ExportFilters` (30–33) and from `parse_filters` (37–89); delete `_parse_role` (140–148), `_parse_career` (92–107), `_ALLOWED_ROLES` (21). Keep `date_*`, `user_ids`, `include`.
- Modify: `app/utils/admin_export_naming.py` — `build_filename_prefix` (58–65) → `f"u{user_id:05d}"` only. Delete `slugify_email`, `email_slug`, `_role_code_and_tenure_kind`, `_region_for`, `_tenure_for`, `_format_tenure_token`, and `NormalizedProfile` (or reduce it to nothing if unused). `normalize_profile_fields` either removed or reduced to a no-op the service no longer calls.
- Modify: `app/services/admin_export_service.py` — `UserContext` (38–46): drop `user_email`, `role`, `profile`; `filename_prefix` from `build_filename_prefix(user_id=...)`. `_collect_users` (138–224): remove UserProfile import (23) + join + role/region/career filters (159–201) + `u.email` usage (211, 215). `_collect_lessonplans` (278–452): glob the new `data/lessonplan/{user_id}/*` layout. `_MANIFEST_COLUMNS` (621–637) & `_USERS_COLUMNS` (639–651): drop `user_email`/`role`/`region`/`tenure`/`tenure_kind`; `build_manifest_csv`/`build_users_csv`/`build_readme` updated to match (no role/region/career summary).
- Modify: `app/routers/admin/exports.py` — endpoint still `Depends(parse_filters)`; nothing else needed once schema drops the fields. (Do **not** touch the dashboard *template* — that's Task 5.) If `app/routers/admin/dashboard.py` reads export params server-side, drop those reads.
- Test: `tests/test_admin_export_service.py`, `tests/unit/test_admin_export_naming.py`, `tests/unit/test_admin_export_filters.py` — rewrite: seed users without email/profile; filename prefix == `u00042`; CSV headers exclude the removed columns; lessonplans seeded under `{user_id}/`; delete role/region/career filter tests.

**Step 1: Write failing tests** — e.g. in `tests/unit/test_admin_export_naming.py`:
```python
from app.utils.admin_export_naming import build_filename_prefix
def test_prefix_is_user_id_only():
    assert build_filename_prefix(user_id=42) == "u00042"
```
and in `tests/unit/test_admin_export_filters.py` assert `parse_filters` rejects/ignores `role` and exposes no `role`/`region`/`career_*` attributes.

**Step 2: Run to verify fail**
Run: `.venv/bin/python -m pytest tests/unit/test_admin_export_naming.py tests/unit/test_admin_export_filters.py tests/test_admin_export_service.py -q`
Expected: FAIL.

**Step 3: Implement** the deletions above.

**Step 4: Verify pass**
Run: same command → PASS. Smoke: `.venv/bin/python -c "import app.services.admin_export_service"`.

**Step 5: Commit**
```bash
git add app/schemas/admin_export.py app/utils/admin_export_naming.py app/services/admin_export_service.py app/routers/admin/exports.py app/routers/admin/dashboard.py tests/test_admin_export_service.py tests/unit/test_admin_export_naming.py tests/unit/test_admin_export_filters.py
git commit -m "refactor(export): remove role/region/career/email; user_id-only naming (#91 §2)"
```

---

### Task 4: §3+§5 — Drop `UserProfile` table & `User.email` column; redefine segment

**Specialist:** backend-engineer
**Depends on:** Task 1 (owns `auth.py`/`qna.py` storage lines — Task 4 edits different lines on the merged result), Task 2 (admin no longer queries UserProfile/email), Task 3 (export no longer queries UserProfile/email)
**Produces:** `user_profiles` table dropped and `users.email` column physically removed at startup; no email-login path; user schemas/segment/constants cleaned.

**Files:**
- Create: `app/migrations/drop_user_profiles.py` — mirror `app/migrations/drop_invite_codes_table.py`: idempotent `DROP TABLE IF EXISTS user_profiles` guarded by an `inspect()` existence check.
- Create: `app/migrations/drop_users_email_column.py` — idempotent: if `email` column exists on `users`, run `DROP INDEX IF EXISTS ix_users_email;` then `ALTER TABLE users DROP COLUMN email;` (modern SQLite supports DROP COLUMN once the unique index is gone — no full table rebuild, FKs untouched). Guard via `inspect(...).get_columns("users")`.
- Modify: `app/migrations/__init__.py` — export the two new functions; remove `ensure_user_profiles_table`.
- Delete: `app/migrations/user_profiles.py`, `app/models/user_profiles.py`.
- Modify: `app/main.py` — drop the `ensure_user_profiles_table` import+call; import+call `drop_user_profiles` and `drop_users_email_column` in the startup sequence (after table-ensures, alongside the other drop).
- Modify: `app/models/users.py` — remove `email` Column (28–30), the `profile` relationship (62–67), and the `UserProfile` import (13).
- Modify: `app/models/__init__.py` — remove `UserProfile` import + `__all__` entry.
- Modify: `app/services/auth_service.py` — delete `get_user_by_email` (314–333), `get_regular_legacy_email_user` (347–356), `authenticate_regular_user_by_legacy_email` (472–484), `normalize_email` (309–312); `_is_login_capable` (343–345) → `return AuthService._has_valid_custom_id(user)`; `create_user` (387–399) drops `email=`.
- Modify: `app/schemas/users.py` — remove `email`/`EmailStr`/`normalize_email_address`/validator (27, 75, 95, 103–109) from `UserCreate`/`UserResponse`.
- Modify: `app/routers/auth.py` — remove the legacy-email login fallback branch (form + server) added by #90; `/auth/register` & `/auth/login` use id only. (Edits the login lines; Task 1 already merged the logout/session lines.)
- Modify: `app/routers/qna.py` — `_session_segment_label_for_user` (72–106): delete the `UserProfile` import (25) and query; return `"미지정"` for new sessions (preserve the legacy nickname→label fallback for invite-code users). New sessions thus record `UNPROFILED_USER_TYPE`.
- Modify: `app/constants.py` — remove `TEACHER_REGIONS`, `PRESERVICE_UNIVERSITY_REGIONS`, `USER_AUTH_ROLES` (all now dead). Keep `UNPROFILED_USER_TYPE`, `SESSION_USER_TYPE_LABELS`, `USER_TYPES`.
- Test: `tests/test_user_id_password_auth.py` — remove legacy-email login tests & email assertions (keep id-login + "no email field" template asserts); `tests/test_auth_middleware_whitelist.py` (72) & `tests/conftest.py` (166) — drop `email=`/profile from fixtures.

**Step 1: Write the failing test** — add `tests/test_schema_cleanup.py`:
```python
import pytest
from sqlalchemy import inspect
from app.db import engine
from app.models.users import User

def test_user_model_has_no_email():
    assert "email" not in User.__table__.columns

def test_userprofile_module_gone():
    with pytest.raises(ModuleNotFoundError):
        __import__("app.models.user_profiles")
```
Plus an async startup-migration test that builds a fresh SQLite, runs `drop_user_profiles`+`drop_users_email_column`, and asserts via `inspect` that the table/column are absent (mirror an existing migration test's harness).

**Step 2: Run to verify fail**
Run: `.venv/bin/python -m pytest tests/test_schema_cleanup.py -q`
Expected: FAIL (email column + module still present).

**Step 3: Implement** migrations, model/schema/auth/segment/constants edits, fixture updates.

**Step 4: Verify pass**
Run: `.venv/bin/python -m pytest tests/test_schema_cleanup.py tests/test_user_id_password_auth.py tests/test_auth_middleware_whitelist.py -q`
Expected: PASS. Startup smoke (fresh DB): `rm -f data/app.db && .venv/bin/python -c "import asyncio, app.main as m; asyncio.run(m.startup_event())"` → no error, logs both drops.

**Step 5: Commit**
```bash
git add app/migrations app/models app/services/auth_service.py app/schemas/users.py app/routers/auth.py app/routers/qna.py app/constants.py app/main.py tests/test_schema_cleanup.py tests/test_user_id_password_auth.py tests/test_auth_middleware_whitelist.py tests/conftest.py
git rm app/migrations/user_profiles.py app/models/user_profiles.py
git commit -m "refactor(auth): drop UserProfile table & User.email column; remove email login (#91 §3,§5)"
```

---

### Task 5: §4 — Templates remove email/role/region/career

**Specialist:** frontend-engineer
**Depends on:** Task 2 (admin JSON no longer returns `email`/`profile`), Task 3 (export params removed), Task 4 (`user.email` removed from model)
**Produces:** All user/admin templates render without `user.email`, profile columns/badges, or export role/region/career inputs.

**Files & exact edits:**
- `app/templates/user/dashboard.html` (235), `viewer.html` (6), `doc_detail.html` (10), `eval_report.html` (10): `{{ user.email or user.nickname }}` → `{{ user.nickname }}`.
- `app/templates/admin/admin_dashboard.html`: nav `{{ user.email }}` (13) → `{{ user.nickname }}`; **delete** export-modal role `<select>` (50–54), region input (59–60), career_min/max inputs (68–74), and the JS that reads/sets `role`/`region`/`career_min`/`career_max` (121–130).
- `app/templates/admin/admin_users.html`: drop the `역할`/`지역·대학교지역`/`경력·학년` `<th>` (131–134) and their cells/badges (351–356); remove `getProfileRole`/`getProfileRegion`/`getProfileCareerOrGrade` helpers (213–233); `accountIdentifier` (321) → `account.user_identifier || account.username`; search placeholder (117) "이메일 또는 ID 검색" → "ID 검색"; help text (110) drop email/role/region/career wording.
- `app/templates/admin/admin_user_detail.html` (127): `data.email || data.username` → `data.username`.
- `app/templates/admin/admin_user_session_detail.html`: remove any 학년/grade profile card (the `m.role`/`msg.role` chat-message refs at 241/285 are `ChatMessage.role` — **leave them**).
- `app/templates/admin/admin_qna_logs.html`: **keep** the `user_type` filter (legacy sessions + "미지정" still valid).

**Step 1–2 (verification is visual/DOM, not unit-tested):** grep-guard. After edits run:
`grep -rnE "user\.email|getProfileRole|career_min|preservice_grade" app/templates/` → expect **no matches** (except intentional `ChatMessage.role`).

**Step 3: Implement** the edits.

**Step 4: Verify**
Run the grep guard (empty) and render-smoke each template via the app if running; otherwise confirm Jinja parses: `.venv/bin/python -c "from jinja2 import Environment, FileSystemLoader; e=Environment(loader=FileSystemLoader('app/templates')); [e.get_template(t) for t in ['user/dashboard.html','admin/admin_users.html','admin/admin_dashboard.html']]"`.

**Step 5: Commit**
```bash
git add app/templates
git commit -m "refactor(ui): remove email/role/region/career from templates (#91 §4)"
```

---

### Task 6: §6 — Docs/specs/scripts reconcile

**Specialist:** docs-engineer
**Depends on:** None (scheduled in Wave 2 for load balance)
**Produces:** Documentation consistent with id-login / no-email / no-profile reality.

**Files & edits:**
- `README.md` (~69–72, ~100): replace admin/user **email** login instructions with **id + password**; remove `admin@example.com` sample.
- `specs/001-ai-rag-eval-platform/contracts/openapi.yaml` (`/auth/login`): `required: [email, password]` → `required: [user_id, password]` (or the id field name the router uses); drop `format: email`.
- `specs/001-ai-rag-eval-platform/data-model.md`, `quickstart.md`: User entity — email NOT NULL login key → id; remove email auth test snippets.
- `docs/MIGRATION_GUIDE.md`: add a header note that the email→username/nickname guide is **superseded** by id-login (#90/#91); do not delete history.
- `docs/plans/2026-05-02-email-password-user-auth-plan.md`, `docs/superpowers/specs/2026-05-18-signup-region-options-design.md`: add a **SUPERSEDED by #91** banner at top (these designed the now-removed email/role/region system).
- `scripts/migrate_to_username_auth.py`: add a top-of-file **DANGER / OBSOLETE — wipes the DB; do not run** banner (do not delete).
- `scripts/create_test_users.py`: confirm it already uses id-only (no change expected); if it sets email/role, remove those.

**Step 1–4:** No unit tests. Verify with `grep -rniE "email.*login|required:\s*\[email" README.md specs/ | cat` → only intentional/historical mentions remain; OpenAPI still valid YAML: `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('specs/001-ai-rag-eval-platform/contracts/openapi.yaml'))"`.

**Step 5: Commit**
```bash
git add README.md specs docs scripts
git commit -m "docs: reconcile specs/README/scripts with id-login & email removal (#91 §6)"
```

---

## Execution

Plan complete and saved to `docs/plans/2026-06-04-issue-91-id-auth-email-removal.md`.

**Recommended: Agent Team-Driven** — Parallel specialist agents (Sonnet), wave-based execution, each in its own worktree; the Opus lead merges each wave into the integration branch, runs the target suite between waves, and after Wave 3 performs the consolidation (full suite + fresh-DB startup migration smoke test) before opening the PR. This matches `team_agents.md`.

**Alternative: Subagent-Driven** — Serial, one fresh subagent per task. Simpler orchestration; slower. Viable since the heavy tasks (1, 4) are backend, but forgoes the Wave-1 / Wave-2 parallelism.

Proceeding with **Agent Team-Driven** per the user's directive (`team_agents.md` + `/writing-plans-for-teams`).
