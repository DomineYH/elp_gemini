# User/Admin Conversation & Report Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the admin "사용자 상세보기" view show the same per-user conversation list and analysis report list that the user sees on their own dashboard, all keyed by the user's email identity.

**Architecture:**
- User-side endpoints (`/api/qna/sessions`, `/api/lessonplan/reports`) already scope by `current_user.id` and the `User.email` column is `unique=True` with `AuthService.normalize_email_address`, so "same email == same user" is already enforced. We add tests to lock the invariant.
- Add new admin-scoped endpoints `GET /admin/api/users/{user_id}/sessions` and `GET /admin/api/users/{user_id}/reports` that reuse the same query shape as the user endpoints, plus a profile summary `GET /admin/api/users/{user_id}`.
- Replace the orphaned `app/templates/admin/admin_user_detail.html` (which references legacy `target_user.documents`) with a real per-user detail page wired to those admin endpoints, mirroring the user dashboard layout (conversations + reports tables, click-through to `/admin/users/session/{id}` and `/admin/reports/view/{id}` which already exist).
- Add a "사용자 상세" link from the accounts table on `/admin/users` to the new page.

**Tech Stack:** FastAPI (async), SQLAlchemy async ORM, Jinja2, Tailwind via CDN, pytest + `httpx.AsyncClient` / `fastapi.testclient.TestClient`.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `app/routers/admin/users.py` | Add 3 endpoints + 1 HTML route for per-user view | Modify |
| `app/templates/admin/admin_user_detail.html` | Replace orphan template; render sessions + reports lists; admin nav | Rewrite |
| `app/templates/admin/admin_users.html` | Add "사용자 상세" link in accounts table | Modify |
| `tests/test_admin_users.py` | Add tests for 3 new endpoints and the HTML route | Modify |
| `tests/test_admin_user_detail_parity.py` | New cross-cutting test: user dashboard and admin view return the same content for the same email | Create |

No new services, repositories, or schemas — the new endpoints reuse `ChatSession`, `ChatMessage`, `AnalysisReport`, `UserProfile`, `User` directly with the same shapes the existing admin endpoints use.

---

## Task 1: Admin per-user sessions endpoint

Add `GET /admin/api/users/{user_id}/sessions` that returns the target user's sessions in the same shape as the user-side `/api/qna/sessions` (paginated, ordered by last activity desc, message_count + last_message_at). The admin route does not require ownership — it requires `get_current_admin`.

**Files:**
- Modify: `app/routers/admin/users.py` (add new endpoint near other `/admin/api/users` routes)
- Test: `tests/test_admin_users.py` (add tests in the same module)

- [ ] **Step 1: Write the failing test (happy path)**

Append to `tests/test_admin_users.py`:

```python
@pytest.mark.asyncio
async def test_admin_user_sessions_returns_target_user_sessions(seed_data):
    """Admin per-user sessions endpoint returns only the target user's sessions, newest first."""
    target_user_id = seed_data["user_id"]
    with TestClient(app) as client:
        resp = client.get(
            f"/admin/api/users/{target_user_id}/sessions"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == target_user_id
    assert body["total_count"] == 2
    assert body["returned_count"] == 2
    titles = [s["title"] for s in body["sessions"]]
    assert titles == ["세션A", "세션B"] or titles == ["세션B", "세션A"]
    # Each item carries message_count + last_message_at (parity with user endpoint)
    for item in body["sessions"]:
        assert "session_id" in item
        assert "message_count" in item
        assert "last_message_at" in item
        assert "created_at" in item
        assert "updated_at" in item


@pytest.mark.asyncio
async def test_admin_user_sessions_pagination(seed_data):
    """limit/offset paginate and has_more flag is set correctly."""
    target_user_id = seed_data["user_id"]
    with TestClient(app) as client:
        resp = client.get(
            f"/admin/api/users/{target_user_id}/sessions?limit=1&offset=0"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["returned_count"] == 1
    assert body["total_count"] == 2
    assert body["has_more"] is True


@pytest.mark.asyncio
async def test_admin_user_sessions_unknown_user_returns_empty(db_tables):
    """Unknown user id returns 404 (not silent empty) to surface bad links."""
    with TestClient(app) as client:
        resp = client.get("/admin/api/users/99999/sessions")
    assert resp.status_code == 404
```

The fixture `seed_data` already returns a dict-like object with `user_id` per the existing module. If it does not, also update the fixture in this step to expose `user_id` and the seeded session titles `세션A`, `세션B`. Read `tests/test_admin_users.py` lines 60–120 first to confirm.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_users.py::test_admin_user_sessions_returns_target_user_sessions tests/test_admin_users.py::test_admin_user_sessions_pagination tests/test_admin_users.py::test_admin_user_sessions_unknown_user_returns_empty -v`

Expected: 3 failures with `404 Not Found` or routing errors (route not defined).

- [ ] **Step 3: Add the endpoint**

Add in `app/routers/admin/users.py` (place after `get_session_detail`, before `get_admin_report_detail`):

```python
from sqlalchemy.orm import aliased  # add at top if missing


@router.get("/admin/api/users/{user_id}/sessions")
async def get_user_sessions_for_admin(
    user_id: int,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자가 특정 사용자의 대화 세션 목록을 조회한다.

    사용자 측 `/api/qna/sessions`와 동일한 정렬/필드 셰입을 반환하되,
    소유권 검사 없이 관리자 권한으로 접근한다.
    """
    user_row = await db.execute(
        select(User.id).where(User.id == user_id)
    )
    if user_row.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )

    stats_session = aliased(ChatSession)
    message_stats = (
        select(
            ChatMessage.session_id,
            func.count(ChatMessage.id).label("message_count"),
            func.max(ChatMessage.created_at).label("last_message_at"),
        )
        .join(stats_session, stats_session.id == ChatMessage.session_id)
        .where(stats_session.user_id == user_id)
        .group_by(ChatMessage.session_id)
        .subquery()
    )

    total_result = await db.execute(
        select(func.count(ChatSession.id)).where(
            ChatSession.user_id == user_id
        )
    )
    total_count = int(total_result.scalar_one() or 0)

    last_activity_at = func.coalesce(
        message_stats.c.last_message_at,
        ChatSession.updated_at,
    )

    result = await db.execute(
        select(
            ChatSession,
            func.coalesce(message_stats.c.message_count, 0).label("message_count"),
            message_stats.c.last_message_at,
        )
        .outerjoin(
            message_stats,
            ChatSession.id == message_stats.c.session_id,
        )
        .where(ChatSession.user_id == user_id)
        .order_by(last_activity_at.desc(), ChatSession.id.desc())
        .offset(offset)
        .limit(limit)
    )

    sessions = []
    for session, message_count, last_message_at in result.all():
        sessions.append({
            "session_id": session.id,
            "title": session.title,
            "user_type": session.user_type,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "message_count": int(message_count or 0),
            "last_message_at": last_message_at.isoformat() if last_message_at else None,
        })

    logger.info(
        "관리자 사용자 세션 목록: admin=%s, target=%s, total=%s",
        current_admin.username, user_id, total_count,
    )
    return {
        "user_id": user_id,
        "sessions": sessions,
        "total_count": total_count,
        "returned_count": len(sessions),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(sessions) < total_count,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_admin_users.py -k "admin_user_sessions" -v`

Expected: 3 passes.

- [ ] **Step 5: Commit**

```bash
git add app/routers/admin/users.py tests/test_admin_users.py
git commit -m "feat(admin): add per-user sessions endpoint mirroring user /api/qna/sessions"
```

---

## Task 2: Admin per-user reports endpoint

Add `GET /admin/api/users/{user_id}/reports` returning the target user's reports in the same shape as `/api/lessonplan/reports`.

**Files:**
- Modify: `app/routers/admin/users.py`
- Test: `tests/test_admin_users.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_users.py`:

```python
@pytest.mark.asyncio
async def test_admin_user_reports_returns_target_user_reports(seed_data):
    """Admin per-user reports endpoint returns only that user's reports, newest first."""
    target_user_id = seed_data["user_id"]
    with TestClient(app) as client:
        resp = client.get(
            f"/admin/api/users/{target_user_id}/reports"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == target_user_id
    assert body["total_count"] == len(body["reports"])
    # Sorted newest first
    if len(body["reports"]) >= 2:
        first = body["reports"][0]["created_at"]
        second = body["reports"][1]["created_at"]
        assert first >= second
    for item in body["reports"]:
        assert {"id", "report_filename", "lessonplan_filename", "created_at"} <= set(item)


@pytest.mark.asyncio
async def test_admin_user_reports_unknown_user_returns_404(db_tables):
    with TestClient(app) as client:
        resp = client.get("/admin/api/users/99999/reports")
    assert resp.status_code == 404
```

If `seed_data` does not currently insert any `AnalysisReport` rows for the target user, extend the fixture to insert 2 reports with distinct `created_at` and `report_filename` values. Mirror the column set already used by `tests/test_admin_users.py::test_admin_report_detail_happy` so the seed shape stays consistent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_users.py -k "admin_user_reports" -v`

Expected: 2 failures (404 routing).

- [ ] **Step 3: Add the endpoint**

Add in `app/routers/admin/users.py` immediately after the sessions endpoint from Task 1:

```python
@router.get("/admin/api/users/{user_id}/reports")
async def get_user_reports_for_admin(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자가 특정 사용자의 분석 보고서 목록을 조회한다.

    사용자 측 `/api/lessonplan/reports`와 동일한 정렬(생성일 desc)·필드를 반환한다.
    """
    user_row = await db.execute(
        select(User.id).where(User.id == user_id)
    )
    if user_row.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )

    total_result = await db.execute(
        select(func.count(AnalysisReport.id)).where(
            AnalysisReport.user_id == user_id
        )
    )
    total_count = int(total_result.scalar_one() or 0)

    result = await db.execute(
        select(AnalysisReport)
        .where(AnalysisReport.user_id == user_id)
        .order_by(AnalysisReport.created_at.desc(), AnalysisReport.id.desc())
        .offset(offset)
        .limit(limit)
    )
    reports = [
        {
            "id": r.id,
            "report_filename": r.report_filename,
            "lessonplan_filename": r.lessonplan_filename,
            "lessonplan_original_name": getattr(r, "lessonplan_original_name", None),
            "latency_ms": r.latency_ms,
            "created_at": r.created_at.isoformat(),
        }
        for r in result.scalars().all()
    ]

    logger.info(
        "관리자 사용자 보고서 목록: admin=%s, target=%s, total=%s",
        current_admin.username, user_id, total_count,
    )
    return {
        "user_id": user_id,
        "reports": reports,
        "total_count": total_count,
        "returned_count": len(reports),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(reports) < total_count,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_admin_users.py -k "admin_user_reports" -v`

Expected: 2 passes.

- [ ] **Step 5: Commit**

```bash
git add app/routers/admin/users.py tests/test_admin_users.py
git commit -m "feat(admin): add per-user reports endpoint mirroring user /api/lessonplan/reports"
```

---

## Task 3: Admin per-user profile summary endpoint

Add `GET /admin/api/users/{user_id}` returning the user's identity + profile + counts, used as the page header on the new admin detail page.

**Files:**
- Modify: `app/routers/admin/users.py`
- Test: `tests/test_admin_users.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_users.py`:

```python
@pytest.mark.asyncio
async def test_admin_user_profile_returns_identity_and_counts(seed_data):
    target_user_id = seed_data["user_id"]
    with TestClient(app) as client:
        resp = client.get(f"/admin/api/users/{target_user_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == target_user_id
    assert body["email"] == "stu1@test.com"
    assert body["username"] == "stu1"
    assert body["is_admin"] is False
    assert body["session_count"] == 2
    assert "report_count" in body
    assert "profile" in body
    assert "summary" in body["profile"]


@pytest.mark.asyncio
async def test_admin_user_profile_unknown_user_returns_404(db_tables):
    with TestClient(app) as client:
        resp = client.get("/admin/api/users/99999")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_users.py -k "admin_user_profile" -v`

Expected: 2 failures.

- [ ] **Step 3: Add the endpoint**

Add in `app/routers/admin/users.py` immediately after the reports endpoint:

```python
@router.get("/admin/api/users/{user_id}")
async def get_user_profile_for_admin(
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 화면 헤더용 사용자 식별/프로필/카운트 조회."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )

    profile_map = await _load_profiles(db, {target.id})
    profile = profile_map.get(target.id, _serialize_profile(None))
    session_counts = await _count_sessions_by_user(db, {target.id})
    report_counts = await _count_reports_by_user(db, {target.id})

    return {
        "user_id": target.id,
        "username": target.username,
        "nickname": target.nickname,
        "email": target.email,
        "is_admin": target.is_admin,
        "created_at": (
            target.created_at.isoformat() if target.created_at else None
        ),
        "profile": profile,
        "session_count": session_counts.get(target.id, 0),
        "report_count": report_counts.get(target.id, 0),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_admin_users.py -k "admin_user_profile" -v`

Expected: 2 passes.

- [ ] **Step 5: Commit**

```bash
git add app/routers/admin/users.py tests/test_admin_users.py
git commit -m "feat(admin): add per-user profile summary endpoint"
```

---

## Task 4: Admin per-user detail HTML route

Replace the orphan template `app/templates/admin/admin_user_detail.html` with a real page that mirrors the user dashboard layout, and add a Jinja-rendered route `GET /admin/users/{user_id}` that returns it.

**Files:**
- Modify: `app/routers/admin/users.py` (add HTML route near `user_session_detail_page`)
- Rewrite: `app/templates/admin/admin_user_detail.html`
- Test: `tests/test_admin_users.py`

- [ ] **Step 1: Write the failing test (route renders shell)**

Append to `tests/test_admin_users.py`:

```python
@pytest.mark.asyncio
async def test_admin_user_detail_page_renders(seed_data):
    target_user_id = seed_data["user_id"]
    with TestClient(app) as client:
        resp = client.get(f"/admin/users/{target_user_id}")
    assert resp.status_code == 200
    html = resp.text
    # Page identifies the target user and hosts both lists
    assert f"data-user-id=\"{target_user_id}\"" in html
    assert "id=\"adminSessionList\"" in html
    assert "id=\"adminReportList\"" in html
    # Calls the three Task 1-3 endpoints
    assert f"/admin/api/users/{target_user_id}/sessions" in html
    assert f"/admin/api/users/{target_user_id}/reports" in html
    assert f"/admin/api/users/{target_user_id}\"" in html or f"/admin/api/users/{target_user_id}'" in html


@pytest.mark.asyncio
async def test_admin_user_detail_page_rejects_unknown_user(db_tables):
    with TestClient(app) as client:
        resp = client.get("/admin/users/99999")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_users.py -k "admin_user_detail_page" -v`

Expected: 2 failures (route not defined).

- [ ] **Step 3: Add the HTML route**

Add in `app/routers/admin/users.py` near `user_session_detail_page` (the `/admin/users/session/{session_id}` route):

```python
@router.get(
    "/admin/users/{user_id}",
    response_class=HTMLResponse,
)
async def admin_user_detail_page(
    request: Request,
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 사용자 상세 페이지(HTML 셸).

    실제 데이터는 페이지 JS가 `/admin/api/users/{user_id}` 계열을 호출한다.
    """
    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )
    result = await db.execute(
        select(User.id).where(User.id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )
    return templates.TemplateResponse(
        "admin/admin_user_detail.html",
        {
            "request": request,
            "user": current_admin,
            "target_user_id": user_id,
        },
    )
```

- [ ] **Step 4: Rewrite the template**

Replace the entire contents of `app/templates/admin/admin_user_detail.html` with:

```html
{% extends "base.html" %}

{% block title %}사용자 상세 - 관리자{% endblock %}

{% block nav_links %}
{% if user.is_admin %}
<a href="/admin/dashboard" class="text-gray-600 hover:text-blue-600">대시보드</a>
<a href="/admin/users" class="text-blue-600 font-medium">사용자</a>
<a href="/admin/qna-logs" class="text-gray-600 hover:text-blue-600">QnA 로그</a>
<a href="/admin/prompts" class="text-gray-600 hover:text-blue-600">프롬프트</a>
<a href="/admin/criteria" class="text-gray-600 hover:text-blue-600">평가기준</a>
{% endif %}
<span class="text-gray-600">{{ user.username }}</span>
<form method="POST" action="/auth/logout" class="inline">
    <button type="submit" class="text-gray-600 hover:text-red-600">로그아웃</button>
</form>
{% endblock %}

{% block content %}
<div class="max-w-6xl mx-auto" data-user-id="{{ target_user_id }}">
    <div class="mb-4">
        <a href="/admin/users" class="text-blue-600 hover:underline">← 사용자 목록</a>
    </div>

    <!-- 사용자 헤더 -->
    <section class="bg-white shadow-md rounded-lg p-6 mb-6" id="userHeader">
        <h1 class="text-2xl font-bold text-gray-900" id="userEmail">불러오는 중...</h1>
        <p class="text-sm text-gray-500 mt-1" id="userMeta">&nbsp;</p>
        <div class="mt-3 flex gap-4 text-sm text-gray-700">
            <span>세션 <strong id="sessionTotal">-</strong></span>
            <span>보고서 <strong id="reportTotal">-</strong></span>
        </div>
    </section>

    <div class="grid gap-6 md:grid-cols-2">
        <!-- 대화 목록 -->
        <section class="bg-white shadow-md rounded-lg p-6">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-xl font-semibold">대화</h2>
                <span class="text-xs text-gray-500" id="sessionCount"></span>
            </div>
            <ul id="adminSessionList" class="divide-y divide-gray-200">
                <li class="py-4 text-sm text-gray-500">로딩 중...</li>
            </ul>
        </section>

        <!-- 보고서 목록 -->
        <section class="bg-white shadow-md rounded-lg p-6">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-xl font-semibold">분석 보고서</h2>
                <span class="text-xs text-gray-500" id="reportCount"></span>
            </div>
            <ul id="adminReportList" class="divide-y divide-gray-200">
                <li class="py-4 text-sm text-gray-500">로딩 중...</li>
            </ul>
        </section>
    </div>
</div>

<script>
const TARGET_USER_ID = {{ target_user_id | tojson }};

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatDate(value) {
    if (!value) return '-';
    try {
        const d = new Date(value);
        if (Number.isNaN(d.getTime())) return value;
        return d.toLocaleString('ko-KR');
    } catch (_) {
        return value;
    }
}

async function loadProfile() {
    const resp = await fetch(`/admin/api/users/${TARGET_USER_ID}`);
    if (!resp.ok) {
        document.getElementById('userEmail').textContent = '사용자를 불러올 수 없습니다.';
        return;
    }
    const data = await resp.json();
    document.getElementById('userEmail').textContent = data.email || data.username;
    const meta = [data.username, data.profile && data.profile.summary].filter(Boolean).join(' · ');
    document.getElementById('userMeta').textContent = meta;
    document.getElementById('sessionTotal').textContent = data.session_count;
    document.getElementById('reportTotal').textContent = data.report_count;
}

async function loadSessions() {
    const list = document.getElementById('adminSessionList');
    const countLabel = document.getElementById('sessionCount');
    const resp = await fetch(`/admin/api/users/${TARGET_USER_ID}/sessions?limit=50&offset=0`);
    if (!resp.ok) {
        list.innerHTML = '<li class="py-4 text-sm text-red-500">세션을 불러올 수 없습니다.</li>';
        return;
    }
    const data = await resp.json();
    countLabel.textContent = `${data.total_count}건`;
    if (!data.sessions.length) {
        list.innerHTML = '<li class="py-4 text-sm text-gray-500">대화가 없습니다.</li>';
        return;
    }
    list.innerHTML = data.sessions.map((s) => `
        <li class="py-3">
            <a href="/admin/users/session/${s.session_id}" class="block hover:bg-gray-50 rounded p-2 -m-2">
                <div class="font-medium text-blue-700">${escapeHtml(s.title || '제목 없음')}</div>
                <div class="text-xs text-gray-500 mt-1">
                    메시지 ${s.message_count} · 최근 ${formatDate(s.last_message_at || s.updated_at || s.created_at)}
                </div>
            </a>
        </li>
    `).join('');
}

async function loadReports() {
    const list = document.getElementById('adminReportList');
    const countLabel = document.getElementById('reportCount');
    const resp = await fetch(`/admin/api/users/${TARGET_USER_ID}/reports?limit=100&offset=0`);
    if (!resp.ok) {
        list.innerHTML = '<li class="py-4 text-sm text-red-500">보고서를 불러올 수 없습니다.</li>';
        return;
    }
    const data = await resp.json();
    countLabel.textContent = `${data.total_count}건`;
    if (!data.reports.length) {
        list.innerHTML = '<li class="py-4 text-sm text-gray-500">보고서가 없습니다.</li>';
        return;
    }
    list.innerHTML = data.reports.map((r) => `
        <li class="py-3">
            <a href="/admin/reports/view/${r.id}" class="block hover:bg-gray-50 rounded p-2 -m-2">
                <div class="font-medium text-blue-700">${escapeHtml(r.lessonplan_original_name || r.report_filename)}</div>
                <div class="text-xs text-gray-500 mt-1">생성일 ${formatDate(r.created_at)}</div>
            </a>
        </li>
    `).join('');
}

document.addEventListener('DOMContentLoaded', () => {
    loadProfile();
    loadSessions();
    loadReports();
});
</script>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_admin_users.py -k "admin_user_detail_page" -v`

Expected: 2 passes.

- [ ] **Step 6: Commit**

```bash
git add app/routers/admin/users.py app/templates/admin/admin_user_detail.html tests/test_admin_users.py
git commit -m "feat(admin): per-user detail page mirroring user dashboard (sessions + reports)"
```

---

## Task 5: Link "사용자 상세" from accounts table

Wire the new per-user page from the existing `/admin/users` accounts table so admins can reach it.

**Files:**
- Modify: `app/templates/admin/admin_users.html`
- Test: `tests/test_admin_users.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_users.py`:

```python
@pytest.mark.asyncio
async def test_admin_users_page_has_per_user_detail_link(seed_data):
    """The accounts table on /admin/users links to the per-user detail page."""
    with TestClient(app) as client:
        resp = client.get("/admin/users")
    assert resp.status_code == 200
    # The accounts row template builds /admin/users/${account.user_id}
    assert "/admin/users/${account.user_id}" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_admin_users.py::test_admin_users_page_has_per_user_detail_link -v`

Expected: FAIL — the link is not yet in the template.

- [ ] **Step 3: Add the link in the accounts table**

In `app/templates/admin/admin_users.html`, locate the accounts table header (around line 130–138):

```html
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">활동</th>
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">가입일</th>
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">비밀번호 변경</th>
```

Insert a new `상세` column header immediately before the "비밀번호 변경" header:

```html
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">활동</th>
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">가입일</th>
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상세</th>
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">비밀번호 변경</th>
```

Then update the empty/loading colspan from `colspan="9"` to `colspan="10"` (two occurrences: the initial row and the error row).

Finally, in the row template inside the `tbody.innerHTML = data.accounts.map((account) => { ... })` block (around line 337–355), insert a new `<td>` right before the password-change `<td>`:

```html
<td class="px-4 py-4 text-sm text-gray-500">${formatDate(account.created_at)}</td>
<td class="px-4 py-4 text-sm">
    <a href="/admin/users/${account.user_id}" class="text-blue-600 hover:underline">상세보기</a>
</td>
<td class="px-4 py-4 text-sm">${passwordAction}</td>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_admin_users.py::test_admin_users_page_has_per_user_detail_link -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/templates/admin/admin_users.html tests/test_admin_users.py
git commit -m "feat(admin): link 사용자 상세보기 from accounts table to per-user page"
```

---

## Task 6: User/admin parity invariant test

Add a single cross-cutting test that proves the user's own dashboard data and the admin's per-user view return the same set of sessions and reports for the same email, and that re-registering with the same email surfaces the same `user_id`.

**Files:**
- Create: `tests/test_admin_user_detail_parity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_user_detail_parity.py`:

```python
"""
Parity invariant: a user's dashboard endpoints and the admin per-user endpoints
must return the same set of sessions and reports when looking at the same user.
Also confirms that User.email is the identity key (same email → same user_id).
"""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, get_db
from app.dependencies import get_current_admin, get_current_user
from app.models.users import User
from app.models.chat_sessions import ChatSession
from app.models.analysis_reports import AnalysisReport
from tests.conftest import (
    TestingSessionLocal,
    override_get_db,
    override_admin,
    engine,
)


_admin = User(
    id=999,
    username="parity_admin",
    nickname="ParityAdmin",
    email="parity_admin@test.com",
    hashed_password="hashed",
    is_admin=True,
)


def _override_current_user(user: User):
    async def _factory():
        return user
    return _factory


@pytest_asyncio.fixture
async def parity_setup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as db:
        owner = User(
            username="parity_user",
            nickname="Parity",
            email="parity_user@test.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add(owner)
        await db.flush()

        s1 = ChatSession(user_id=owner.id, user_type="1학년", title="대화1")
        s2 = ChatSession(user_id=owner.id, user_type="2학년", title="대화2")
        db.add_all([s1, s2])

        r1 = AnalysisReport(
            user_id=owner.id,
            lessonplan_filename="lp1.pdf",
            lessonplan_original_name="지도안1.pdf",
            report_filename="report1.md",
            report_path="/tmp/report1.md",
            latency_ms=1000,
        )
        r2 = AnalysisReport(
            user_id=owner.id,
            lessonplan_filename="lp2.pdf",
            lessonplan_original_name="지도안2.pdf",
            report_filename="report2.md",
            report_path="/tmp/report2.md",
            latency_ms=1200,
        )
        db.add_all([r1, r2])
        await db.commit()
        owner_id = owner.id

    yield {"owner_id": owner_id}

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_user_dashboard_and_admin_view_return_same_sessions(parity_setup):
    owner_id = parity_setup["owner_id"]

    async with TestingSessionLocal() as db:
        owner = await db.get(User, owner_id)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_admin(_admin)
    app.dependency_overrides[get_current_user] = _override_current_user(owner)
    try:
        with TestClient(app) as client:
            user_resp = client.get("/api/qna/sessions?limit=50&offset=0")
            admin_resp = client.get(f"/admin/api/users/{owner_id}/sessions?limit=50&offset=0")
        assert user_resp.status_code == 200
        assert admin_resp.status_code == 200
        user_ids = sorted(s["session_id"] for s in user_resp.json()["sessions"])
        admin_ids = sorted(s["session_id"] for s in admin_resp.json()["sessions"])
        assert user_ids == admin_ids
        assert user_resp.json()["total_count"] == admin_resp.json()["total_count"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_user_dashboard_and_admin_view_return_same_reports(parity_setup):
    owner_id = parity_setup["owner_id"]

    async with TestingSessionLocal() as db:
        owner = await db.get(User, owner_id)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_admin(_admin)
    app.dependency_overrides[get_current_user] = _override_current_user(owner)
    try:
        with TestClient(app) as client:
            user_resp = client.get("/api/lessonplan/reports")
            admin_resp = client.get(f"/admin/api/users/{owner_id}/reports?limit=100&offset=0")
        assert user_resp.status_code == 200
        assert admin_resp.status_code == 200
        user_ids = sorted(r["id"] for r in user_resp.json()["reports"])
        admin_ids = sorted(r["id"] for r in admin_resp.json()["reports"])
        assert user_ids == admin_ids
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_same_email_resolves_to_same_user_id(parity_setup):
    """이메일 정규화로 같은 이메일은 같은 user_id를 가리킨다."""
    from app.services.auth_service import AuthService
    owner_id = parity_setup["owner_id"]
    async with TestingSessionLocal() as db:
        svc = AuthService(db)
        found_lower = await svc.get_user_by_email("parity_user@test.com")
        found_upper = await svc.get_user_by_email("PARITY_USER@TEST.COM")
    assert found_lower is not None
    assert found_upper is not None
    assert found_lower.id == owner_id
    assert found_upper.id == owner_id
```

- [ ] **Step 2: Run tests to verify they fail (if Tasks 1–4 are not yet merged) or pass**

Run: `pytest tests/test_admin_user_detail_parity.py -v`

Expected when Tasks 1–4 are merged: 3 passes. If run before, the first two fail at `404` for `/admin/api/users/{id}/sessions|reports`. This task is the final gate.

- [ ] **Step 3: Commit**

```bash
git add tests/test_admin_user_detail_parity.py
git commit -m "test: assert user dashboard and admin per-user view are equivalent for same email"
```

---

## Task 7: Manual smoke and final commit

- [ ] **Step 1: Start the dev server**

Run: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

- [ ] **Step 2: Verify user view**

Log in as a normal user (or use `admin@example.com` if you only have admin), visit `/dashboard`, confirm:
- "내 세션" list shows the user's sessions
- "내 보고서" list shows the user's reports
- Clicking a session opens history; clicking a report opens `/reports/view/{id}`

- [ ] **Step 3: Verify admin view**

Log in as admin, visit `/admin/users`, on the accounts table click "상세보기" for the user above. Confirm:
- The page header shows the user's email + counts
- The 대화 list has the same items as the user dashboard
- The 분석 보고서 list has the same items as the user dashboard
- Clicking a session goes to `/admin/users/session/{id}` (existing, untouched)
- Clicking a report opens `/admin/reports/view/{id}` (existing, untouched)

If anything diverges, file a follow-up against this plan rather than patching ad hoc.

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/test_admin_users.py tests/test_admin_user_detail_parity.py -v`

Expected: all green.

- [ ] **Step 5: No commit needed**

Manual verification only.

---

## Self-Review Notes

- Coverage:
  - Requirement "사용자 입장 — 같은 이메일이면 같은 사용자, 대화/보고서 목록, 클릭 시 내용 확인" → Tasks 6 (parity test, email normalization invariant). No code change required for the user side because the existing endpoints already meet the spec.
  - Requirement "관리자 입장 — 사용자 상세보기 시 사용자와 동일한 view" → Tasks 1, 2, 3 (API), 4 (page), 5 (link), 6 (parity test).
- No placeholders: every code step contains the literal code to add; every test step contains assertion code.
- Type/name consistency: endpoints all return `user_id`, `total_count`, `returned_count`, `has_more`. The HTML template references those exact keys. `loadSessions` / `loadReports` / `loadProfile` are defined together in the template.
- No new shared abstractions introduced; the new endpoints use the existing helpers `_load_profiles`, `_serialize_profile`, `_count_sessions_by_user`, `_count_reports_by_user` already in `app/routers/admin/users.py`.

---

## Execution

Plan complete and saved to `docs/plans/2026-05-11-user-conversation-report-parity.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks.
2. **Inline Execution** — batch execution with checkpoints.

Which approach?
