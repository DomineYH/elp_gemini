# 관리자 사용자 관리 — 라벨/색상 통일 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**계획 작성:** Opus 4.7
**구현(코딩) 담당:** Sonnet (별도 세션에서 본 plan을 task 단위로 실행)
**기반 spec:** `docs/superpowers/specs/2026-05-12-admin-user-role-label-color-unification-design.md` (commit `63f2e09`)

**Goal:** 관리자 사용자 관리(`/admin/users`)의 세션 유형 라벨 `현직교사`를 `교사`로 통일하고, 역할/세션 유형 배지 색상을 시각적으로 일관되도록 변경한다.

**Architecture:** (1) 백엔드 상수/라우터에서 라벨 문자열을 갱신하고, (2) startup-time 멱등 마이그레이션 헬퍼로 기존 DB 데이터를 일괄 갱신하며, (3) 프론트엔드 템플릿의 select 옵션과 `getBadgeClass` 색상 매핑을 갱신한다. 사용자/구현 코드 인터페이스 변경 없음(라벨 문자열만 교체).

**Tech Stack:** FastAPI, SQLAlchemy (async), Jinja2, Tailwind CSS, pytest (+ pytest-asyncio), aiosqlite

---

## File Structure

| 파일 | 역할 | 변경 유형 |
|---|---|---|
| `app/migrations/chat_sessions_user_type_rename.py` | DB 라벨 정규화 헬퍼 | **신규** |
| `app/migrations/__init__.py` | 헬퍼 export | 수정 |
| `app/main.py` | startup에서 헬퍼 호출 | 수정 |
| `app/constants.py` | `SESSION_USER_TYPE_LABELS` 라벨 | 수정 |
| `app/routers/qna.py` | 세션 user_type 기록 시 라벨 | 수정 |
| `app/models/chat_sessions.py` | 컬럼 docstring | 수정 |
| `app/templates/admin/admin_users.html` | 필터 옵션, `getBadgeClass` 색상 매핑 | 수정 |
| `tests/test_user_history_endpoints.py` | 기존 fixture 라벨 | 수정 |
| `tests/test_chat_sessions_user_type_rename.py` | 마이그레이션 헬퍼 테스트 | **신규** |

---

## Task 1: 마이그레이션 헬퍼 — failing test 작성

**Files:**
- Test: `tests/test_chat_sessions_user_type_rename.py` (신규)

- [ ] **Step 1: 테스트 파일 생성**

```python
"""chat_sessions.user_type 라벨 정규화 마이그레이션 테스트"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import rename_chat_session_in_service_teacher_label


async def _create_chat_sessions_table(engine):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE chat_sessions ("
                "id INTEGER PRIMARY KEY, "
                "user_id INTEGER, "
                "title VARCHAR(255), "
                "user_type VARCHAR(50), "
                "created_at DATETIME, "
                "updated_at DATETIME)"
            )
        )


async def _insert_user_type(engine, value):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO chat_sessions (user_type) VALUES (:v)"
            ),
            {"v": value},
        )


async def _count_user_type(engine, value):
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM chat_sessions WHERE user_type = :v"
            ),
            {"v": value},
        )
        return result.scalar_one()


@pytest.mark.asyncio
async def test_renames_hyunjik_to_kyosa(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await _create_chat_sessions_table(engine)
    await _insert_user_type(engine, "현직교사")
    await _insert_user_type(engine, "현직교사")
    await _insert_user_type(engine, "1학년")

    updated = await rename_chat_session_in_service_teacher_label(engine)

    assert updated == 2
    assert await _count_user_type(engine, "현직교사") == 0
    assert await _count_user_type(engine, "교사") == 2
    assert await _count_user_type(engine, "1학년") == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await _create_chat_sessions_table(engine)
    await _insert_user_type(engine, "현직교사")

    first = await rename_chat_session_in_service_teacher_label(engine)
    second = await rename_chat_session_in_service_teacher_label(engine)

    assert first == 1
    assert second == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_no_rows_to_rename(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await _create_chat_sessions_table(engine)
    await _insert_user_type(engine, "1학년")
    await _insert_user_type(engine, "교사")

    updated = await rename_chat_session_in_service_teacher_label(engine)

    assert updated == 0
    assert await _count_user_type(engine, "1학년") == 1
    assert await _count_user_type(engine, "교사") == 1

    await engine.dispose()
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `uv run pytest tests/test_chat_sessions_user_type_rename.py -v`

Expected: 모두 실패. `ImportError: cannot import name 'rename_chat_session_in_service_teacher_label' from 'app.migrations'`

---

## Task 2: 마이그레이션 헬퍼 구현

**Files:**
- Create: `app/migrations/chat_sessions_user_type_rename.py`
- Modify: `app/migrations/__init__.py`

- [ ] **Step 1: 헬퍼 모듈 생성**

`app/migrations/chat_sessions_user_type_rename.py`:

```python
"""
chat_sessions.user_type 라벨 정규화: '현직교사' → '교사'
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def rename_chat_session_in_service_teacher_label(
    engine: AsyncEngine,
) -> int:
    """
    chat_sessions.user_type의 '현직교사' 레코드를 '교사'로 일괄 갱신.

    Returns:
        갱신된 행 수. 멱등이므로 두 번째 호출부터는 0.
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE chat_sessions "
                "SET user_type = '교사' "
                "WHERE user_type = '현직교사'"
            )
        )
        updated = result.rowcount or 0
        if updated:
            logger.info(
                "chat_sessions.user_type '현직교사' → '교사' 갱신 행 수: %d",
                updated,
            )
        return updated
```

- [ ] **Step 2: `app/migrations/__init__.py`에 등록**

기존 import 블록 아래에 추가하고 `__all__`에도 등록:

```python
from .chat_sessions_user_type_rename import (
    rename_chat_session_in_service_teacher_label,
)
```

`__all__` 리스트에 다음 항목 추가:

```python
"rename_chat_session_in_service_teacher_label",
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `uv run pytest tests/test_chat_sessions_user_type_rename.py -v`

Expected: 3개 테스트 모두 PASS.

- [ ] **Step 4: 커밋**

```bash
git add app/migrations/chat_sessions_user_type_rename.py \
        app/migrations/__init__.py \
        tests/test_chat_sessions_user_type_rename.py
git commit -m "$(cat <<'EOF'
feat(migrations): rename chat_sessions.user_type '현직교사' → '교사'

idempotent startup-time helper, three new tests covering rename, idempotency, and no-op cases.

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: startup에서 마이그레이션 호출

**Files:**
- Modify: `app/main.py:25-28` (imports), `app/main.py:191-211` (startup_event body)

- [ ] **Step 1: import 추가**

`app/main.py:25-28` 영역의 import 블록에 다음 항목 추가:

```python
from app.migrations import (
    ensure_criteria_file_path_column,
    ensure_criteria_display_alias_column,
    ensure_user_profiles_table,
    ensure_users_lockout_columns,
    rename_chat_session_in_service_teacher_label,
)
```

(기존 import 행 끝에 `rename_chat_session_in_service_teacher_label`만 추가하면 된다.)

- [ ] **Step 2: startup_event에 호출 추가**

`app/main.py:207-211`의 `profiles_patched` 블록 직후에 다음 블록 추가:

```python
    renamed = await rename_chat_session_in_service_teacher_label(engine)
    if renamed:
        logger.info(
            "chat_sessions.user_type '현직교사' → '교사' 갱신: %d 행",
            renamed,
        )
```

- [ ] **Step 3: 앱 import smoke test**

Run: `uv run python -c "from app.main import app; print('ok')"`

Expected: `ok` 출력 (import 에러 없음).

- [ ] **Step 4: 커밋**

```bash
git add app/main.py
git commit -m "$(cat <<'EOF'
feat(startup): call chat_sessions user_type rename helper

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 백엔드 라벨 갱신 — constants

**Files:**
- Modify: `app/constants.py:3-9`

- [ ] **Step 1: 코드 변경**

`app/constants.py`의 `SESSION_USER_TYPE_LABELS` 리스트에서 `"현직교사"`를 `"교사"`로 교체:

```python
SESSION_USER_TYPE_LABELS = [
    "1학년",
    "2학년",
    "3학년",
    "4학년",
    "교사",
]
```

- [ ] **Step 2: 잔존 참조 검색**

Run: `grep -rn "현직교사" app --include="*.py" | grep -v __pycache__`

Expected: `app/routers/qna.py`, `app/models/chat_sessions.py` 두 파일만 남음 (다음 task에서 처리).

- [ ] **Step 3: 커밋 보류**

이 단계는 task 5와 함께 커밋한다 (논리적 단위 묶음).

---

## Task 5: 백엔드 라벨 갱신 — qna.py & chat_sessions 모델

**Files:**
- Modify: `app/routers/qna.py:93`, `app/routers/qna.py:102`
- Modify: `app/models/chat_sessions.py:58`

- [ ] **Step 1: `app/routers/qna.py:90-105` 갱신**

해당 영역 (`_derive_session_user_type` 함수 내부)에서 두 곳의 반환 문자열을 갱신:

```python
        if profile_role == "teacher":
            return "교사"
```

```python
    if nickname == "teacher":
        return "교사"
```

(주의: `if profile_role == "preservice_teacher":` 블록의 `f"{preservice_grade}학년"` 및 `"미지정"` 반환은 그대로 둔다.)

- [ ] **Step 2: `app/models/chat_sessions.py:56-59` 컬럼 docstring 갱신**

```python
        comment=(
            "세션 세그먼트 라벨 "
            "(1학년, 2학년, 3학년, 4학년, 교사)"
        )
```

- [ ] **Step 3: 잔존 참조 재검색**

Run: `grep -rn "현직교사" app --include="*.py" | grep -v __pycache__`

Expected: 결과 없음 (마이그레이션 헬퍼 내부 SQL의 WHERE 절은 의도된 잔존 — `app/migrations/chat_sessions_user_type_rename.py`).

Run: `grep -rn "현직교사" app/migrations --include="*.py" | grep -v __pycache__`

Expected: `app/migrations/chat_sessions_user_type_rename.py`의 UPDATE 문 안에만 존재 — 정상.

- [ ] **Step 4: 커밋**

```bash
git add app/constants.py app/routers/qna.py app/models/chat_sessions.py
git commit -m "$(cat <<'EOF'
refactor(session-labels): rename '현직교사' → '교사' across backend

constants.SESSION_USER_TYPE_LABELS, qna router segment derivation, ChatSession.user_type column docstring.

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 기존 테스트 fixture 갱신

**Files:**
- Modify: `tests/test_user_history_endpoints.py:86`

- [ ] **Step 1: fixture 라벨 갱신**

`tests/test_user_history_endpoints.py:86`의 `user_type="현직교사"`를 다음과 같이 변경:

```python
            user_type="교사",
```

- [ ] **Step 2: 잔존 참조 재검색**

Run: `grep -rn "현직교사" tests --include="*.py" | grep -v __pycache__`

Expected: 결과 없음.

- [ ] **Step 3: 해당 테스트 파일 실행**

Run: `uv run pytest tests/test_user_history_endpoints.py -v`

Expected: 모든 테스트 PASS. (라벨 변경이 단언문에 직접 사용되지 않는 fixture라면 단순 픽스처 갱신으로 충분.)

만약 expected 값으로 사용된 곳이 있다면 동일하게 `"교사"`로 갱신한다. 다음 명령으로 잔존을 확인:

Run: `grep -n "현직교사\|kyosa" tests/test_user_history_endpoints.py`

- [ ] **Step 4: 커밋**

```bash
git add tests/test_user_history_endpoints.py
git commit -m "$(cat <<'EOF'
test(user-history): align fixture user_type label with rename

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 프론트엔드 — 필터 옵션 라벨 변경

**Files:**
- Modify: `app/templates/admin/admin_users.html:95`

- [ ] **Step 1: select 옵션 갱신**

`app/templates/admin/admin_users.html:95` 라인을 다음으로 변경:

```html
                <option value="교사">교사</option>
```

- [ ] **Step 2: 잔존 참조 재검색**

Run: `grep -n "현직교사" app/templates/admin/admin_users.html`

Expected: 결과 없음(이 task에서 마지막 잔존을 제거).

---

## Task 8: 프론트엔드 — 배지 색상 매핑 변경

**Files:**
- Modify: `app/templates/admin/admin_users.html:184-197`

- [ ] **Step 1: `getBadgeClass` 매핑 교체**

기존 `184-197` 영역 (현재):

```javascript
function getBadgeClass(userType) {
    const classes = {
        '1학년': 'bg-blue-100 text-blue-800',
        '2학년': 'bg-green-100 text-green-800',
        '3학년': 'bg-yellow-100 text-yellow-800',
        '4학년': 'bg-purple-100 text-purple-800',
        '현직교사': 'bg-red-100 text-red-800',
        'teacher': 'bg-emerald-100 text-emerald-800',
        'preservice_teacher': 'bg-indigo-100 text-indigo-800',
        '교사': 'bg-emerald-100 text-emerald-800',
        '예비교사': 'bg-indigo-100 text-indigo-800',
    };
    return classes[userType] || 'bg-gray-100 text-gray-800';
}
```

변경 후:

```javascript
function getBadgeClass(userType) {
    const classes = {
        '1학년': 'bg-indigo-50 text-indigo-700',
        '2학년': 'bg-indigo-100 text-indigo-800',
        '3학년': 'bg-indigo-200 text-indigo-900',
        '4학년': 'bg-indigo-300 text-indigo-900',
        'teacher': 'bg-red-100 text-red-800',
        'preservice_teacher': 'bg-indigo-100 text-indigo-800',
        '교사': 'bg-red-100 text-red-800',
        '예비교사': 'bg-indigo-100 text-indigo-800',
    };
    return classes[userType] || 'bg-gray-100 text-gray-800';
}
```

변경 포인트:
- `1~4학년` blue/green/yellow/purple → indigo 50/100/200/300 (연→진)
- `현직교사` 키 제거 (라벨이 더 이상 존재하지 않음)
- `teacher` / `교사` 값을 emerald → red로 변경
- `preservice_teacher` / `예비교사` 는 유지

- [ ] **Step 2: 커밋**

```bash
git add app/templates/admin/admin_users.html
git commit -m "$(cat <<'EOF'
feat(admin-users-ui): rename 현직교사 label and unify badge colors

- 세션 유형 필터: 현직교사 → 교사
- 교사(역할 + 세션 유형): red 통일
- 1~4학년: indigo 4단계 (연→진)
- 예비교사: indigo 유지

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 전체 테스트 실행

**Files:** (변경 없음)

- [ ] **Step 1: 관련 테스트만 우선 실행**

Run:
```bash
uv run pytest tests/test_chat_sessions_user_type_rename.py \
              tests/test_user_history_endpoints.py \
              tests/test_admin_users.py -v
```

Expected: 모두 PASS.

- [ ] **Step 2: 전체 테스트 스위트**

Run: `uv run pytest -x --ignore=tests/integration`

Expected: 모두 PASS. (실패 시 라벨 관련 단언 또는 fixture 누락 가능성 — grep으로 `현직교사` 잔존 재확인.)

- [ ] **Step 3: 잔존 `현직교사` 최종 점검**

Run:
```bash
grep -rn "현직교사" app tests --include="*.py" --include="*.html" | grep -v __pycache__
```

Expected: `app/migrations/chat_sessions_user_type_rename.py`의 SQL WHERE 절 1줄만 출력.

---

## Task 10: 수동 검증 (UI)

**Files:** (변경 없음)

- [ ] **Step 1: 로컬 서버 기동**

Run: `make run` 또는 `uv run uvicorn app.main:app --reload`

- [ ] **Step 2: startup 로그 확인**

서버 콘솔에서 다음 메시지 중 하나가 나타나는지 확인:
- `chat_sessions.user_type '현직교사' → '교사' 갱신: N 행` (기존 데이터 있는 경우)
- 또는 로그 없음 (마이그레이션 대상 행이 없는 경우 — 정상)

- [ ] **Step 3: 관리자 로그인 후 `/admin/users` 접속**

- [ ] **Step 4: 시각 검증 체크리스트**

- [ ] 세션 세그먼트 필터 select에 `교사` 옵션이 있고 `현직교사`는 없다.
- [ ] 사용자 계정 목록 > 역할 컬럼:
  - `교사` 배지가 빨간색(`bg-red-100`)으로 표시된다.
  - `예비교사` 배지가 indigo 색으로 표시된다.
- [ ] 세션 목록 > 세션 유형 컬럼:
  - `교사` 배지가 빨간색으로 표시된다 (역할 배지와 동일 색).
  - `1학년` ~ `4학년` 배지가 indigo 4단계로 연→진 표시된다.
- [ ] 필터에서 `교사` 선택 시 세션이 올바르게 필터링된다.

- [ ] **Step 5: 검증 결과를 PR 본문에 기록**

위 체크리스트 결과 스크린샷 또는 텍스트 기록을 PR 본문 또는 issue 코멘트에 첨부.

---

## Task 11: PR 작성

**Files:** (브랜치 작업)

- [ ] **Step 1: 브랜치 생성 (또는 worktree 사용)**

```bash
git checkout -b feat/admin-users-label-color-unification
```

(이미 별도 브랜치/worktree에서 작업 중이라면 생략)

- [ ] **Step 2: push & PR 생성**

```bash
git push -u origin feat/admin-users-label-color-unification
gh pr create --title "feat(admin-users): '현직교사' → '교사' 라벨 통일 및 색상 일관성" --body "$(cat <<'EOF'
## Summary
- 세션 유형 라벨 `현직교사` → `교사`로 통일
- 사용자 계정 목록의 역할 배지와 세션 유형 배지의 색상 일관성 확보 (교사 = red, 예비교사/1~4학년 = indigo 계열)
- 기존 DB의 `chat_sessions.user_type='현직교사'` 레코드를 startup-time 멱등 마이그레이션으로 일괄 갱신

## Related
- Spec: `docs/superpowers/specs/2026-05-12-admin-user-role-label-color-unification-design.md`
- Plan: `docs/superpowers/plans/2026-05-12-admin-user-role-label-color-unification.md`
- Issue: #(이슈 번호)

## Test plan
- [ ] `uv run pytest tests/test_chat_sessions_user_type_rename.py -v`
- [ ] `uv run pytest tests/test_user_history_endpoints.py tests/test_admin_users.py -v`
- [ ] `uv run pytest -x --ignore=tests/integration`
- [ ] 로컬 서버에서 `/admin/users` 수동 시각 검증 (필터, 역할 배지 색, 세션 유형 배지 색)
- [ ] startup 로그에서 마이그레이션 실행 메시지 확인

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: PR URL을 사용자에게 보고**

---

## 검증 기준 (spec과 매핑)

| spec §7 | task |
|---|---|
| 1. 기존 테스트 통과 | Task 9 |
| 2-a. 필터 옵션 `교사` 보이고 `현직교사` 없음 | Task 7 + Task 10 |
| 2-b. 역할 컬럼 색 (`교사`=red, `예비교사`=indigo) | Task 8 + Task 10 |
| 2-c. 세션 유형 색 (`교사`=red, 1~4학년=indigo 4단계) | Task 8 + Task 10 |
| 3. DB에 `현직교사` 잔존 0건 | Task 2, 3 + Task 10 startup 로그 |
| 4. 신규 세션 user_type = `교사` 기록 | Task 5 |
| 5. 마이그레이션 헬퍼 멱등성 | Task 1 (`test_idempotent`) |

---

## Self-Review 메모

- **Spec coverage**: spec §5의 6개 라벨 변경, 9개 색상 매핑, DB 마이그레이션, 검증 기준 5개가 모두 위 task로 매핑됨.
- **Placeholders**: 없음. 모든 step에 실제 코드/명령 포함.
- **Type consistency**: 헬퍼 함수명 `rename_chat_session_in_service_teacher_label`은 Task 1 테스트, Task 2 구현, Task 3 startup 호출에서 동일.
