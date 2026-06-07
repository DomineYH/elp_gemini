# 설문 게이트 기반 보고서 획득 차단 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분석 보고서의 영구 획득(전용 페이지 열람·인쇄·PDF·.md 다운로드·목록 보기)을 사용자당 1회 설문 완료(자가 확인) 후로 서버 측 하드 차단한다. 방금 분석한 결과는 모달에 1회 표시 허용.

**Architecture:** `users.survey_completed_at`(nullable) 1컬럼으로 완료 여부를 영속화. `POST /api/survey/complete`가 자가 확인을 기록(멱등). 보고서 JSON/다운로드 엔드포인트는 미완료 시 403. 전용 보고서 페이지는 미완료 시 본문 대신 설문 게이트를 렌더. `/analyze`는 변경하지 않는다(방금 결과 1회 표시 유지). 기준 스펙: `docs/superpowers/specs/2026-06-07-survey-gated-report-access-design.md`.

**Tech Stack:** FastAPI, SQLAlchemy(async), Jinja2, SQLite, pytest/pytest-asyncio, httpx AsyncClient.

---

## File Structure

- `app/models/users.py` — `survey_completed_at` 컬럼 추가.
- `app/migrations/users_survey_completed_column.py` (신규) — `ensure_users_survey_completed_column(engine)`.
- `app/migrations/__init__.py` — export 추가.
- `app/main.py` — import + startup 호출.
- `app/routers/survey.py` (신규) — `POST /api/survey/complete`.
- `app/routers/lessonplan_analysis.py` — 보고서 JSON/다운로드 403 게이트.
- `app/routers/views.py` — 전용 페이지 컨텍스트에 `survey_completed`.
- `app/templates/user/report_viewer.html` — 미완료 시 설문 게이트.
- `app/templates/user/dashboard.html` — `completeSurvey()`가 완료를 서버에 기록.
- `tests/test_survey_completion.py` (신규) — 완료 엔드포인트 + 게이트 403 테스트.
- `tests/test_users_survey_completed_migration.py` (신규) — 마이그레이션 테스트.

---

## Task 1: `users.survey_completed_at` 모델 컬럼 + 마이그레이션

**Files:**
- Modify: `app/models/users.py`
- Create: `app/migrations/users_survey_completed_column.py`
- Modify: `app/migrations/__init__.py`
- Modify: `app/main.py`
- Test: `tests/test_users_survey_completed_migration.py`

- [ ] **Step 1: 마이그레이션 실패 테스트 작성**

Create `tests/test_users_survey_completed_migration.py`:

```python
"""users.survey_completed_at 컬럼 보정 마이그레이션 검증 (issue: 설문 게이트)."""
import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.migrations.users_survey_completed_column import (
    ensure_users_survey_completed_column,
)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # survey_completed_at 없는 구버전 users 테이블 생성
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, "
                "username TEXT NOT NULL, "
                "nickname TEXT NOT NULL, "
                "hashed_password TEXT, "
                "is_admin BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
    yield eng
    await eng.dispose()


def _columns(sync_conn):
    return {c["name"] for c in inspect(sync_conn).get_columns("users")}


@pytest.mark.asyncio
async def test_adds_survey_completed_at_column(engine):
    added = await ensure_users_survey_completed_column(engine)
    assert added is True
    async with engine.begin() as conn:
        cols = await conn.run_sync(_columns)
    assert "survey_completed_at" in cols


@pytest.mark.asyncio
async def test_idempotent(engine):
    await ensure_users_survey_completed_column(engine)
    again = await ensure_users_survey_completed_column(engine)
    assert again is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_users_survey_completed_migration.py -q`
Expected: FAIL (ModuleNotFoundError: app.migrations.users_survey_completed_column)

- [ ] **Step 3: 마이그레이션 구현**

Create `app/migrations/users_survey_completed_column.py`:

```python
"""
설문 게이트용 users 테이블 컬럼 보정

추가 컬럼:
- survey_completed_at: 참여 설문 완료 시각 (NULL=미완료)
"""
from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _collect_users_columns(sync_conn) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        columns = inspector.get_columns("users")
    except NoSuchTableError:
        return None
    return {col["name"] for col in columns}


async def ensure_users_survey_completed_column(engine: AsyncEngine) -> bool:
    """
    users 테이블에 survey_completed_at 컬럼 추가

    Returns:
        새 컬럼을 추가하면 True, 이미 있으면 False
    """
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_users_columns)

        if columns is None:
            logger.warning(
                "users 테이블이 없어 survey_completed_at 패치를 건너뜀"
            )
            return False

        if "survey_completed_at" in columns:
            return False

        await conn.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN survey_completed_at DATETIME"
            )
        )
        logger.info("users.survey_completed_at 컬럼 추가")
        return True
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_users_survey_completed_migration.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: 모델에 컬럼 추가**

In `app/models/users.py`, after the `last_failed_login_at = Column(DateTime, nullable=True)` line, add:

```python
    survey_completed_at = Column(DateTime, nullable=True)
```

(`DateTime` is already imported.)

- [ ] **Step 6: 마이그레이션 export 등록**

In `app/migrations/__init__.py`:
- Add import after the `users_lockout_columns` import line:
```python
from .users_survey_completed_column import (
    ensure_users_survey_completed_column,
)
```
- Add `"ensure_users_survey_completed_column",` into the `__all__` list (next to `"ensure_users_lockout_columns",`).

- [ ] **Step 7: startup 호출 등록**

In `app/main.py`:
- Add `ensure_users_survey_completed_column,` into the `from app.migrations import (...)` block (alphabetically near `ensure_users_lockout_columns`).
- In `startup_event()`, right after the `lockout_patched = await ensure_users_lockout_columns(engine)` block (after its `if lockout_patched:` log), add:
```python
    survey_col_patched = await ensure_users_survey_completed_column(engine)
    if survey_col_patched:
        logger.info(
            "users.survey_completed_at 컬럼이 자동 추가되었습니다."
        )
```

- [ ] **Step 8: import 정상 확인 + 커밋**

Run: `.venv/bin/python -c "import app.main; print('ok')"`
Expected: prints `ok`

```bash
git add app/models/users.py app/migrations/users_survey_completed_column.py app/migrations/__init__.py app/main.py tests/test_users_survey_completed_migration.py
git commit -m "feat(survey): users.survey_completed_at 컬럼 + 마이그레이션"
```

---

## Task 2: 설문 완료 기록 엔드포인트 `POST /api/survey/complete`

**Files:**
- Create: `app/routers/survey.py`
- Modify: `app/main.py`
- Test: `tests/test_survey_completion.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_survey_completion.py`:

```python
"""설문 완료 엔드포인트 + 보고서 게이트 403 테스트."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.users import User


def _make_client(user: User):
    async def override_get_user():
        return user

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def uncompleted_user():
    return User(id=1, username="tester", hashed_password="x")


@pytest.mark.asyncio
async def test_complete_survey_records(uncompleted_user):
    assert uncompleted_user.survey_completed_at is None
    async with _make_client(uncompleted_user) as c:
        res = await c.post("/api/survey/complete")
    assert res.status_code == 200
    assert res.json()["survey_completed"] is True
    assert uncompleted_user.survey_completed_at is not None
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_complete_survey_idempotent(uncompleted_user):
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    uncompleted_user.survey_completed_at = fixed
    async with _make_client(uncompleted_user) as c:
        res = await c.post("/api/survey/complete")
    assert res.status_code == 200
    assert uncompleted_user.survey_completed_at == fixed
    app.dependency_overrides.clear()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_survey_completion.py -q`
Expected: FAIL (404, 라우트 없음)

- [ ] **Step 3: 라우터 구현**

Create `app/routers/survey.py`:

```python
"""설문 참여 완료 기록 라우터 (자가 확인, 사용자당 1회)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.users import User

router = APIRouter(prefix="/api/survey", tags=["survey"])


@router.post("/complete")
async def complete_survey(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """참여 설문 완료를 기록한다. 이미 완료면 그대로(멱등)."""
    if current_user.survey_completed_at is None:
        current_user.survey_completed_at = datetime.now(timezone.utc)
        db.add(current_user)
        await db.commit()
    return {"success": True, "survey_completed": True}
```

- [ ] **Step 4: 라우터 등록**

In `app/main.py`:
- Add `survey,` to the routers import block (where `views,` `qna,` etc. are imported — find `from app.routers import (` or individual imports and match the existing style).
- Add `app.include_router(survey.router)` next to the other `app.include_router(...)` calls (near `app.include_router(lessonplan_analysis.router)`).

> NOTE: match the exact import style already used in main.py for routers (e.g. `from app.routers import (auth, qna, ...)` or per-module imports). Inspect the file's existing router imports first and follow it.

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_survey_completion.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: 커밋**

```bash
git add app/routers/survey.py app/main.py tests/test_survey_completion.py
git commit -m "feat(survey): POST /api/survey/complete 자가확인 기록 엔드포인트"
```

---

## Task 3: 보고서 JSON/다운로드 엔드포인트 설문 게이트 (403)

**Files:**
- Modify: `app/routers/lessonplan_analysis.py`
- Test: `tests/test_survey_completion.py` (append)

- [ ] **Step 1: 게이트 403 실패 테스트 추가**

Append to `tests/test_survey_completion.py`:

```python
@pytest.mark.asyncio
async def test_report_json_blocked_without_survey(uncompleted_user):
    async with _make_client(uncompleted_user) as c:
        res = await c.get("/api/lessonplan/reports/10")
    assert res.status_code == 403
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_report_download_blocked_without_survey(uncompleted_user):
    async with _make_client(uncompleted_user) as c:
        res = await c.get("/api/lessonplan/reports/10/download")
    assert res.status_code == 403
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_report_json_allowed_after_survey(tmp_path):
    """완료 사용자는 게이트를 통과한다(403 아님)."""
    from unittest.mock import MagicMock, patch

    completed = User(
        id=1, username="tester", hashed_password="x",
        survey_completed_at=datetime.now(timezone.utc),
    )
    report_file = tmp_path / "r.md"
    report_file.write_text("# 보고서 본문", encoding="utf-8")

    fake_report = MagicMock()
    fake_report.id = 10
    fake_report.lessonplan_filename = "lp.pdf"
    fake_report.lessonplan_original_name = "lp.pdf"
    fake_report.report_filename = "r.md"
    fake_report.report_path = str(report_file)
    fake_report.latency_ms = 1000
    fake_report.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = fake_report

    async def override_get_user():
        return completed

    db = AsyncMock()
    db.execute = AsyncMock(return_value=exec_result)

    async def override_get_db():
        yield db

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/api/lessonplan/reports/10")
    assert res.status_code == 200
    assert res.json()["content"] == "# 보고서 본문"
    app.dependency_overrides.clear()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_survey_completion.py -q`
Expected: FAIL (게이트 미구현 → 403 대신 다른 코드)

- [ ] **Step 3: 게이트 헬퍼 + 적용**

In `app/routers/lessonplan_analysis.py`:
- After the `router = APIRouter(...)` line (around line 24), add the helper:
```python


def _require_survey_completed(user: User) -> None:
    """설문 미완료면 403. 보고서 영구 획득 경로 보호."""
    if user.survey_completed_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="설문 참여 후 보고서를 열람할 수 있습니다.",
        )
```
- In `get_analysis_report(...)`, as the FIRST statement inside the function body (before the `try:`), add:
```python
    _require_survey_completed(current_user)
```
- In `download_analysis_report(...)`, as the FIRST statement inside the function body (before the `try:`), add:
```python
    _require_survey_completed(current_user)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_survey_completion.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add app/routers/lessonplan_analysis.py tests/test_survey_completion.py
git commit -m "feat(survey): 보고서 JSON/다운로드 미완료 시 403 게이트"
```

---

## Task 4: 전용 페이지 컨텍스트에 `survey_completed` 전달

**Files:**
- Modify: `app/routers/views.py`

- [ ] **Step 1: 컨텍스트 추가**

In `app/routers/views.py`, in `view_analysis_report(...)`, the `templates.TemplateResponse("user/report_viewer.html", {...})` context dict: add a key so it becomes:
```python
    return templates.TemplateResponse(
        "user/report_viewer.html",
        {
            "request": request,
            "user": current_user,
            "report_id": report_id,
            "survey_completed": current_user.survey_completed_at is not None,
        },
    )
```

- [ ] **Step 2: import 정상 확인 + 커밋**

Run: `.venv/bin/python -c "import app.main; print('ok')"`
Expected: prints `ok`

```bash
git add app/routers/views.py
git commit -m "feat(survey): 전용 보고서 페이지 컨텍스트에 survey_completed 전달"
```

---

## Task 5: 전용 보고서 페이지에 설문 게이트

**Files:**
- Modify: `app/templates/user/report_viewer.html`

미완료(`survey_completed=false`)면 본문 대신 설문 게이트를 보여주고, 인쇄/다운로드 액션을 숨긴다. 완료 클릭 → `POST /api/survey/complete` → `location.reload()`(서버가 이제 `survey_completed=true`로 렌더 → 본문 fetch + `?print=1` 자동 인쇄).

- [ ] **Step 1: 액션바를 완료 여부로 분기**

In `app/templates/user/report_viewer.html`, the action bar (the `<div class="mb-4 flex items-center justify-between gap-4 flex-wrap no-print">`). Wrap the right-side `<div class="flex items-center gap-3">...</div>` (download link + 인쇄 버튼) and the hint `<p>` in `{% if survey_completed %} ... {% endif %}` so they only render when completed. The "← 대시보드로 돌아가기" link stays unconditional. Result:

```html
    <div class="mb-4 flex items-center justify-between gap-4 flex-wrap no-print">
        <a href="/dashboard" class="text-blue-600 hover:underline text-sm">
            ← 대시보드로 돌아가기
        </a>
        {% if survey_completed %}
        <div class="flex items-center gap-3">
            <a id="downloadLink"
               href="/api/lessonplan/reports/{{ report_id }}/download"
               class="text-sm text-gray-600 hover:text-blue-600 underline">
                원본(.md) 다운로드
            </a>
            <button type="button" onclick="window.print()"
                    class="text-sm bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700">
                인쇄 / PDF 저장
            </button>
        </div>
        {% endif %}
    </div>
    {% if survey_completed %}
    <p class="text-xs text-gray-400 mb-4 no-print">인쇄가 안 되면 브라우저 메뉴 → 인쇄, 또는 '원본(.md) 다운로드'를 이용하세요.</p>
    {% endif %}
```

- [ ] **Step 2: 본문 영역을 완료 여부로 분기 + 게이트 블록 추가**

Replace the `<header>` + `<section>` content blocks so that, when not completed, a gate is shown instead. Wrap the existing `<header class="...">...</header>` and `<section class="...">...</section>` in `{% if survey_completed %} ... {% endif %}`, then add an `{% else %}` gate:

```html
    {% if survey_completed %}
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
    {% else %}
    <section class="bg-white shadow-sm rounded-lg p-8 text-center no-print">
        <h1 class="text-xl font-bold text-gray-900 mb-3">설문 참여가 필요합니다</h1>
        <p class="text-gray-600 mb-6">
            보고서 열람·인쇄·저장은 참여 설문을 완료하신 후 이용할 수 있습니다.<br>
            아래 '설문 참여하기'로 설문을 마친 뒤 '설문참여 완료'를 눌러주세요.
        </p>
        <div class="flex items-center justify-center gap-3">
            <button type="button" id="surveyGateParticipate"
                    class="bg-indigo-600 text-white px-6 py-2 rounded hover:bg-indigo-700">
                설문 참여하기
            </button>
            <button type="button" id="surveyGateComplete"
                    class="bg-gray-600 text-white px-6 py-2 rounded hover:bg-gray-700">
                설문참여 완료
            </button>
        </div>
    </section>
    {% endif %}
```

- [ ] **Step 3: 스크립트 분기**

In the `<script>` block, replace the final `loadReport().then(...)` invocation (added in PR #125) with a survey-aware branch. Use the existing form URL (same as dashboard):

```javascript
    const SURVEY_COMPLETED = {{ 'true' if survey_completed else 'false' }};
    const SURVEY_FORM_URL = 'https://forms.gle/PmnzRSGqUMURr7mJ7';

    if (SURVEY_COMPLETED) {
        loadReport().then(() => {
            if (new URLSearchParams(location.search).get('print') === '1') {
                window.print();
            }
        });
    } else {
        const participateBtn = document.getElementById('surveyGateParticipate');
        const completeBtn = document.getElementById('surveyGateComplete');
        if (participateBtn) {
            participateBtn.addEventListener('click', () => {
                window.open(SURVEY_FORM_URL, '_blank', 'noopener');
            });
        }
        if (completeBtn) {
            completeBtn.addEventListener('click', async () => {
                completeBtn.disabled = true;
                try {
                    await fetch('/api/survey/complete', {
                        method: 'POST',
                        credentials: 'same-origin',
                    });
                } catch (e) {
                    /* best-effort: 실패해도 reload로 재시도 가능 */
                }
                location.reload();
            });
        }
    }
```

> NOTE: `loadReport`, `escapeHtml`, `renderSafeMarkdown` 등 기존 함수 정의는 그대로 둔다(완료 분기에서 사용). 완료 안 된 경우 `loadReport`는 호출되지 않으므로 본문 fetch(403) 자체가 일어나지 않는다.

- [ ] **Step 4: 커밋**

```bash
git add app/templates/user/report_viewer.html
git commit -m "feat(survey): 전용 보고서 페이지 미완료 시 설문 게이트"
```

---

## Task 6: 대시보드 설문 완료를 서버에 기록

**Files:**
- Modify: `app/templates/user/dashboard.html`

- [ ] **Step 1: `completeSurvey()`가 서버에 기록하도록 수정**

In `app/templates/user/dashboard.html`, replace the existing `completeSurvey()` function:

```javascript
    function completeSurvey() {
        closeSurveyModal();
        closeAnalysisModal();
    }
```

with:

```javascript
    async function completeSurvey() {
        try {
            await fetch('/api/survey/complete', {
                method: 'POST',
                credentials: 'same-origin',
            });
        } catch (e) {
            /* best-effort */
        }
        closeSurveyModal();
        closeAnalysisModal();
    }
```

(`participateSurvey()`는 변경하지 않는다.)

- [ ] **Step 2: 커밋**

```bash
git add app/templates/user/dashboard.html
git commit -m "feat(survey): 대시보드 설문 완료를 서버에 기록"
```

---

## Task 7: 전체 회귀 확인

- [ ] **Step 1: 신규 테스트 모두 통과**

Run: `.venv/bin/python -m pytest tests/test_survey_completion.py tests/test_users_survey_completed_migration.py -q`
Expected: PASS (전부 통과)

- [ ] **Step 2: 수집 에러 baseline 유지 확인**

Run: `.venv/bin/python -m pytest --co -q 2>&1 | tail -2`
Expected: `... errors` 개수가 **23**(기존 baseline)과 동일. 24 이상이면 신규 수집 에러를 도입한 것이므로 원인 파일을 수정.

- [ ] **Step 3: report_id 회귀(PR #125) 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_lessonplan_analysis_service.py -q -k "report_id or ReportId"`
Expected: PASS (2 passed)

---

## Self-Review (작성자 점검 완료)

- **Spec coverage:** 데이터모델(T1)·완료기록(T2)·JSON/다운로드 403(T3)·뷰 컨텍스트(T4)·뷰어 게이트(T5)·대시보드 기록(T6)·회귀(T7) → 스펙 전 항목 매핑됨. `/analyze` 무변경(스펙 일치).
- **Placeholder scan:** 모든 코드 스텝에 실제 코드 포함. main.py 라우터 import는 파일 기존 스타일을 따르라는 NOTE만 명시(스타일이 환경마다 다를 수 있어 의도적).
- **Type consistency:** `survey_completed_at`(모델/마이그레이션/엔드포인트/컨텍스트), `ensure_users_survey_completed_column`(생성/​export/​startup), `survey_completed`(컨텍스트/​템플릿 `SURVEY_COMPLETED`) 일관.
- **회귀 리스크:** `/analyze` 미변경으로 기존 analyze 테스트 무영향. 게이트는 신규 엔드포인트/신규 동작이라 기존 통과 테스트에 영향 없음.
