# Admin Analysis Report Viewer Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use agent-team-driven-development to execute this plan.

**Goal:** Admin clicks "보고서 보기" on `/admin/users/session/{id}` and gets a rendered analysis report instead of `{"detail":"Not Found"}`.

**Architecture:** Add an admin-only JSON API (`/admin/api/reports/{id}`) and HTML viewer (`/admin/reports/view/{id}`) that bypass the owner check enforced by `/api/lessonplan/reports/{id}`. The admin session-detail template stops pointing at `/static/${report_path}` (which double-prefixes the on-disk path `app/static/reports/...`) and instead links to the new viewer. The viewer reuses the user-side rendering / markdown sanitisation patterns.

**Tech Stack:** FastAPI (async), SQLAlchemy 2.x async, Jinja2, vanilla JS + `marked.js`, pytest + `TestClient`.

---

## Wave Analysis

### Specialists

| Role | Expertise | Tasks |
|------|-----------|-------|
| backend-engineer | FastAPI routes, SQLAlchemy async, pytest+TestClient | Tasks 1, 2, 5 |
| frontend-engineer | Jinja2 templates, vanilla JS, Tailwind | Tasks 3, 4 |

### Waves

**Wave 1: Foundations** — independent building blocks for the new viewer
- Task 1 (backend-engineer) — Admin JSON API `GET /admin/api/reports/{report_id}`
- Task 4 (frontend-engineer) — New Jinja template `admin/admin_report_viewer.html`

  *Parallel-safe because:* Task 1 only edits `app/routers/admin/users.py` (Python). Task 4 creates a brand-new file `app/templates/admin/admin_report_viewer.html`. They share no import path and no file.

**Wave 2: Wiring** — needs Wave 1 outputs
- Task 2 (backend-engineer) — HTML viewer route `GET /admin/reports/view/{report_id}` that renders the Wave-1 template and the page fetches the Wave-1 JSON API

  *Depends on Wave 1:* JSON URL `/admin/api/reports/{id}` from Task 1 (consumed by the template's `fetch`) and template path `admin/admin_report_viewer.html` from Task 4.

**Wave 3: Integration + verification** — needs Wave 2 route live
- Task 3 (frontend-engineer) — Repoint admin session detail link from broken `/static/${report_path}` to `/admin/reports/view/${id}`
- Task 5 (backend-engineer) — Add pytest coverage in `tests/test_admin_users.py` (authz + happy path + missing report + missing file)

  *Parallel-safe because:* Task 3 edits `app/templates/admin/admin_user_session_detail.html`; Task 5 edits `tests/test_admin_users.py`. Disjoint files, no import relationship.
  *Depends on Wave 2:* the viewer URL `/admin/reports/view/{id}` must exist for both the template link to work and the test assertions to be meaningful.

### Dependency Graph

```
T1 ──┐         ┌──→ T3
     ├──→ T2 ──┤
T4 ──┘         └──→ T5
```

---

## Task 1: Admin JSON API for report content

**Specialist:** backend-engineer
**Depends on:** None
**Produces:** `GET /admin/api/reports/{report_id}` returning `{id, lessonplan_filename, lessonplan_original_name, report_filename, content, latency_ms, created_at}`. Returns 404 when the report row or the on-disk file is missing; 403 (via `get_current_admin`) when the caller is not an admin.

**Files:**
- Modify: `app/routers/admin/users.py` (add handler, add `from pathlib import Path`)

**Step 1: Add the import**

Insert near the existing imports at the top of `app/routers/admin/users.py`:

```python
from pathlib import Path
```

**Step 2: Implement the endpoint**

Append after `get_session_detail` (after line ~648):

```python
@router.get("/admin/api/reports/{report_id}")
async def get_admin_report_detail(
    report_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 전용 분석 보고서 상세 조회 (소유자 우회).

    `app.routers.lessonplan_analysis.get_analysis_report`와 동일한 응답
    스키마를 반환하되, `AnalysisReport.user_id == current_user.id` 검사를
    수행하지 않는다. 관리자 권한 검증은 `get_current_admin`이 담당한다.
    """
    result = await db.execute(
        select(AnalysisReport).where(AnalysisReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="보고서를 찾을 수 없습니다.",
        )

    report_path = Path(report.report_path)
    if not report_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="보고서 파일이 존재하지 않습니다.",
        )

    content = report_path.read_text(encoding="utf-8")
    logger.info(
        "관리자 보고서 조회: admin=%s, report_id=%s",
        current_admin.username,
        report_id,
    )
    return {
        "id": report.id,
        "lessonplan_filename": report.lessonplan_filename,
        "lessonplan_original_name": report.lessonplan_original_name,
        "report_filename": report.report_filename,
        "content": content,
        "latency_ms": report.latency_ms,
        "created_at": report.created_at.isoformat(),
    }
```

**Step 3: Smoke-check existing suite still passes**

Run: `.venv/bin/pytest tests/test_admin_users.py -x -q`
Expected: existing tests pass (real assertions added in Task 5).

**Step 4: Commit**

```bash
git add app/routers/admin/users.py
git commit -m "feat(admin): add admin JSON API to read any analysis report"
```

---

## Task 2: Admin report viewer HTML route

**Specialist:** backend-engineer
**Depends on:** Task 1 (JSON URL `/admin/api/reports/{id}`), Task 4 (template `admin/admin_report_viewer.html`)
**Produces:** `GET /admin/reports/view/{report_id}` returning an HTML shell that loads the Task-1 JSON and renders Markdown. Rejects `report_id <= 0` with 404. Available only to admins (via `get_current_admin`).

**Files:**
- Modify: `app/routers/admin/users.py`

**Step 1: Implement**

Append after the Task-1 handler:

```python
@router.get(
    "/admin/reports/view/{report_id}",
    response_class=HTMLResponse,
)
async def admin_report_viewer_page(
    request: Request,
    report_id: int,
    current_admin: User = Depends(get_current_admin),
):
    """관리자 분석 보고서 뷰어 페이지 (HTML shell).

    실제 보고서 존재 검증은 페이지 내 `fetch`가 호출하는
    `/admin/api/reports/{report_id}`에서 수행한다.
    """
    if report_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="보고서를 찾을 수 없습니다.",
        )
    return templates.TemplateResponse(
        "admin/admin_report_viewer.html",
        {
            "request": request,
            "user": current_admin,
            "report_id": report_id,
        },
    )
```

**Step 2: Manual smoke**

```bash
.venv/bin/uvicorn app.main:app --reload
# Authenticate as admin, visit /admin/reports/view/1 → 200 HTML
```

**Step 3: Commit**

```bash
git add app/routers/admin/users.py
git commit -m "feat(admin): add HTML route for admin analysis report viewer"
```

---

## Task 3: Update admin session detail link

**Specialist:** frontend-engineer
**Depends on:** Task 2 (viewer route exists)
**Produces:** "보고서 보기" anchor in the admin session detail page navigates to `/admin/reports/view/{report.id}` (opens in a new tab) instead of the broken `/static/${report_path}` URL.

**Files:**
- Modify: `app/templates/admin/admin_user_session_detail.html:336-372`

**Step 1: Rewrite the URL builder**

Locate the existing block:

```js
const reportUrl =
    r.report_path
        ? `/static/${r.report_path}`
        : '#';
```

Replace with:

```js
const reportUrl =
    Number.isInteger(r.id) && r.id > 0
        ? `/admin/reports/view/${r.id}`
        : '#';
```

Keep the `target="_blank"` attribute. The `report_path` field is no longer used in rendering and may be left alone in the API response (avoid touching the backend response shape from this task).

**Step 2: Manual verification (golden path + edge case)**

1. Log in as admin (`/admin/users`).
2. Open a session via "상세보기".
3. Click "보고서 보기" on a report card.
4. Expected: new tab opens at `/admin/reports/view/{id}` and the report markdown renders. No JSON `{"detail":"Not Found"}` page.
5. Force a missing-id case by editing the rendered DOM to `r.id = 0` → link should be `#` (no navigation).

**Step 3: Commit**

```bash
git add app/templates/admin/admin_user_session_detail.html
git commit -m "fix(admin): point session report link to admin viewer instead of static path"
```

---

## Task 4: Admin report viewer Jinja template

**Specialist:** frontend-engineer
**Depends on:** None at build time (consumes Task 1's JSON URL at runtime)
**Produces:** `app/templates/admin/admin_report_viewer.html` extending `base.html`, rendering the same markdown viewer UX as `user/report_viewer.html` but with admin nav and pointing to `/admin/api/reports/{id}`.

**Files:**
- Create: `app/templates/admin/admin_report_viewer.html`

**Step 1: Author the template**

Use `app/templates/user/report_viewer.html` as the base. Differences:

- Title block: `분석 보고서 (관리자) - AI 문서 평가 플랫폼`.
- Back link: `← 사용자 관리로 돌아가기` → `/admin/users`.
- Drop the `원본(.md) 다운로드` anchor (admin viewer scope is "read"; download not part of this fix).
- Fetch URL inside `loadReport`: `/admin/api/reports/${REPORT_ID}` instead of `/api/lessonplan/reports/${REPORT_ID}`.
- Keep `escapeHtml`, `isSafeMarkdownUrl`, `sanitizeRenderedMarkdown`, `renderSafeMarkdown`, `formatDate` verbatim (XSS/markdown sanitisation must stay intact).

Skeleton:

```html
{% extends "base.html" %}

{% block title %}분석 보고서 (관리자) - AI 문서 평가 플랫폼{% endblock %}

{% block head %}
<style>
    /* identical prose styles from user/report_viewer.html */
</style>
{% endblock %}

{% block content %}
<div class="max-w-4xl mx-auto">
    <div class="mb-4">
        <a href="/admin/users" class="text-blue-600 hover:underline text-sm">
            ← 사용자 관리로 돌아가기
        </a>
    </div>

    <header class="bg-white shadow-sm rounded-lg p-6 mb-4">
        <h1 id="reportTitle" class="text-2xl font-bold text-gray-900 break-all">
            보고서 불러오는 중...
        </h1>
        <p id="reportMeta" class="text-sm text-gray-500 mt-2">&nbsp;</p>
    </header>

    <section class="bg-white shadow-sm rounded-lg p-6">
        <article id="reportContent" class="prose max-w-none text-gray-800">
            <p class="text-gray-500 text-center py-8">보고서를 불러오는 중...</p>
        </article>
    </section>
</div>
{% endblock %}

{% block scripts %}
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
    const REPORT_ID = {{ report_id | int }};

    // escapeHtml / isSafeMarkdownUrl / sanitizeRenderedMarkdown /
    // renderSafeMarkdown / formatDate — copy verbatim from
    // app/templates/user/report_viewer.html

    async function loadReport() {
        const titleEl = document.getElementById('reportTitle');
        const metaEl = document.getElementById('reportMeta');
        const contentEl = document.getElementById('reportContent');
        try {
            const res = await fetch(`/admin/api/reports/${REPORT_ID}`, {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' },
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            const title = data.report_filename
                || data.lessonplan_original_name
                || `보고서 #${REPORT_ID}`;
            titleEl.textContent = title;
            document.title = `${title} - AI 문서 평가 플랫폼`;

            const lesson = data.lessonplan_original_name
                || data.lessonplan_filename
                || '';
            const created = formatDate(data.created_at);
            metaEl.textContent = [lesson, created].filter(Boolean).join(' · ');

            contentEl.innerHTML = renderSafeMarkdown(data.content);
        } catch (err) {
            contentEl.innerHTML =
                '<p class="text-red-600 text-center py-8">보고서를 불러올 수 없습니다.</p>';
            console.error('보고서 로드 실패:', err);
        }
    }

    loadReport();
</script>
{% endblock %}
```

**Step 2: Static lint**

```bash
.venv/bin/python -c "from jinja2 import Environment, FileSystemLoader; \
  Environment(loader=FileSystemLoader('app/templates')).get_template('admin/admin_report_viewer.html')"
```
Expected: no exception (template parses).

**Step 3: Commit**

```bash
git add app/templates/admin/admin_report_viewer.html
git commit -m "feat(admin): add admin analysis report viewer template"
```

---

## Task 5: Pytest coverage for admin endpoints

**Specialist:** backend-engineer
**Depends on:** Task 1, Task 2
**Produces:** Regression tests in `tests/test_admin_users.py` covering:
- Admin can read another user's report (happy path).
- 404 when `report_id` does not exist.
- 404 when row exists but file is missing.
- 403 when caller is not an admin.
- Viewer page renders 200 and embeds the expected `REPORT_ID`.

**Files:**
- Modify: `tests/test_admin_users.py`

**Step 1: Add tests**

Use the existing `_override_deps` fixture and `TestingSessionLocal`. Create an `AnalysisReport` row pointing at a temp markdown file (or a missing path). Example skeletons:

```python
import pathlib
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_admin, get_current_user
from app.models.analysis_reports import AnalysisReport
from tests.conftest import TestingSessionLocal


@pytest.mark.asyncio
async def test_admin_get_report_returns_content(tmp_path):
    report_file = tmp_path / "victim_20260511_x_reports.md"
    report_file.write_text("# 보고서\n내용", encoding="utf-8")

    async with TestingSessionLocal() as session:
        # create non-admin user, then report row referencing report_file
        # commit
        ...

    client = TestClient(app)
    resp = client.get(f"/admin/api/reports/{report.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"].startswith("# 보고서")
    assert body["report_filename"] == report.report_filename


@pytest.mark.asyncio
async def test_admin_get_report_404_when_row_missing():
    client = TestClient(app)
    resp = client.get("/admin/api/reports/999999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_get_report_404_when_file_missing(tmp_path):
    # report row points at tmp_path / "missing.md" (do NOT create it)
    ...
    resp = client.get(f"/admin/api/reports/{report.id}")
    assert resp.status_code == 404
    assert "파일이 존재하지 않습니다" in resp.json()["detail"]


def test_admin_get_report_forbidden_for_non_admin(monkeypatch):
    # override get_current_admin → raises 403, mirroring real auth chain
    ...
    client = TestClient(app)
    resp = client.get("/admin/api/reports/1")
    assert resp.status_code == 403


def test_admin_report_viewer_page_renders():
    client = TestClient(app)
    resp = client.get("/admin/reports/view/1")
    assert resp.status_code == 200
    assert "REPORT_ID = 1" in resp.text
    assert "/admin/api/reports/" in resp.text
```

Mirror the existing test file's setup conventions (DB override, `_admin` fixture, `app.dependency_overrides`).

**Step 2: Run**

```bash
.venv/bin/pytest tests/test_admin_users.py -x -q
```
Expected: all new tests pass; no regressions.

**Step 3: Commit**

```bash
git add tests/test_admin_users.py
git commit -m "test(admin): cover analysis report endpoints (authz, 404, render)"
```

---

## Execution

Plan complete and saved to `docs/plans/2026-05-11-admin-analysis-report-fix.md`.

**Recommended: Agent Team-Driven** — Wave 1 runs Tasks 1 + 4 in parallel (backend & frontend specialists), Wave 2 wires the route, Wave 3 finishes the link swap and tests in parallel.

**Alternative: Subagent-Driven** — Serial execution for a single contributor; viable since the total scope is ~5 small changes.

Which approach?
