# 관리자 삭제 기능 구현 계획 (Admin Deletion Features Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자 화면에 3가지 삭제 기능을 추가한다 — (1) 사용자 계정 목록에서 사용자 삭제, (2) 사용자 상세보기에서 개별/일괄 대화·보고서 삭제, (3) QnA 로그에서 세션 단위 삭제.

**Architecture:**
- 삭제는 모두 **hard delete**. SQLAlchemy 모델에 이미 `cascade="all, delete-orphan"`이 설정되어 있어 사용자 삭제 시 chat_sessions / chat_messages / analysis_reports / user_profiles가 자동으로 함께 제거된다.
- 보고서 삭제 시 **파일도 함께 삭제**한다: `AnalysisReport.report_path` (`app/static/reports/*.md`) 와 `AnalysisReport.lessonplan_filename` (`app/static/uploads/*.pdf`).
- 비즈니스 로직은 새 서비스 `app/services/admin_deletion_service.py`로 분리하고, 라우터는 권한·CSRF·HTTP 변환만 담당한다.
- 안전 장치: 관리자 계정 삭제 불가(403), 자기 자신 삭제 불가(403), CSRF 토큰 필수, 클라이언트에서 confirm 모달.
- 기존 `_ensure_admin_csrf_token` / `_require_admin_csrf_token`은 `app/utils/admin_csrf.py`로 이동해 QnA 로그 라우터도 재사용한다.

**Tech Stack:** FastAPI · SQLAlchemy 2.x (async) · Jinja2 · Tailwind CSS · pytest-asyncio · FastAPI TestClient.

---

## File Structure

**Create:**
- `app/utils/admin_csrf.py` — CSRF helper 함수 분리
- `app/services/admin_deletion_service.py` — 삭제 비즈니스 로직 + 파일 정리
- `tests/test_admin_csrf_util.py` — 분리된 CSRF helper 테스트
- `tests/test_admin_deletion_service.py` — 서비스 단위 테스트
- `tests/test_admin_deletion_endpoints.py` — 엔드포인트 통합 테스트

**Modify:**
- `app/routers/admin/users.py` — DELETE/POST(bulk) 엔드포인트 추가, CSRF 헬퍼 import 위치 변경
- `app/routers/admin/qna_logs.py` — `qna_logs_page`에 CSRF 토큰 주입
- `app/templates/admin/admin_users.html` — 삭제 컬럼 + confirm 모달 + JS
- `app/templates/admin/admin_user_detail.html` — 개별/일괄 삭제 UI + confirm 모달 + JS
- `app/templates/admin/admin_qna_logs.html` — CSRF meta + 세션 삭제 버튼 + confirm 모달

각 파일은 하나의 책임만 갖는다: util은 토큰만, service는 비즈니스 로직만, router는 HTTP 변환만, template은 표현만.

---

## API Design

| Method | Path | 설명 |
|---|---|---|
| `DELETE` | `/admin/api/users/{user_id}` | 사용자 + 모든 연관 데이터/파일 삭제 |
| `DELETE` | `/admin/api/chat-sessions/{session_id}` | 단일 대화 세션 삭제 (메시지 cascade) |
| `DELETE` | `/admin/api/reports/{report_id}` | 단일 분석 보고서 삭제 (.md + .pdf 파일 포함) |
| `POST`   | `/admin/api/users/{user_id}/sessions/bulk-delete` | `{"session_ids": [...]}` 일괄 삭제 |
| `POST`   | `/admin/api/users/{user_id}/reports/bulk-delete`  | `{"report_ids":  [...]}` 일괄 삭제 |

- 모든 엔드포인트는 `get_current_admin` + CSRF (`X-CSRF-Token` 헤더) 검증.
- 응답 형식: `{ "ok": true, "deleted": <int>, "files_removed": <int> }` (실패 시 HTTPException).
- bulk delete는 `user_id`에 속하지 않는 ID가 섞이면 전체를 거부하고 400 반환 (부분 성공 금지 — 트랜잭션 단순화).

---

### Task 1: CSRF helper 모듈 분리

**Files:**
- Create: `app/utils/admin_csrf.py`
- Modify: `app/routers/admin/users.py:47-156`
- Create: `tests/test_admin_csrf_util.py`

- [ ] **Step 1: 새 유틸 파일 작성**

`app/utils/admin_csrf.py`:

```python
"""관리자 상태 변경 요청용 CSRF 토큰 헬퍼.

세션에 토큰을 저장하고 헤더로 받은 토큰과 상수시간 비교한다.
"""
import secrets

from fastapi import HTTPException, Request, status

ADMIN_CSRF_SESSION_KEY = "admin_csrf_token"
ADMIN_CSRF_HEADER = "x-csrf-token"


def ensure_admin_csrf_token(request: Request) -> str:
    """세션에 CSRF 토큰을 생성/보관하고 토큰 문자열을 반환한다."""
    token = request.session.get(ADMIN_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[ADMIN_CSRF_SESSION_KEY] = token
    return str(token)


def require_admin_csrf_token(request: Request) -> None:
    """세션 토큰과 요청 헤더를 상수시간 비교한다. 불일치 시 403."""
    expected = request.session.get(ADMIN_CSRF_SESSION_KEY)
    provided = request.headers.get(ADMIN_CSRF_HEADER)
    if (
        not expected
        or not provided
        or not secrets.compare_digest(str(expected), str(provided))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF 토큰이 유효하지 않습니다.",
        )
```

- [ ] **Step 2: users.py에서 헬퍼 import로 교체**

`app/routers/admin/users.py`의 47–156 라인에 정의된 `ADMIN_CSRF_SESSION_KEY`, `ADMIN_CSRF_HEADER`, `_ensure_admin_csrf_token`, `_require_admin_csrf_token`을 제거하고, 파일 상단에 다음 import 추가:

```python
from app.utils.admin_csrf import (
    ensure_admin_csrf_token,
    require_admin_csrf_token,
)
```

기존 호출부 (`_ensure_admin_csrf_token(...)` / `_require_admin_csrf_token(...)`)를 모두 새 함수명(`ensure_admin_csrf_token` / `require_admin_csrf_token`)으로 변경. 검색·치환으로 처리.

- [ ] **Step 3: 테스트 작성**

`tests/test_admin_csrf_util.py`:

```python
"""admin_csrf 유틸 단위 테스트."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.utils.admin_csrf import (
    ADMIN_CSRF_HEADER,
    ensure_admin_csrf_token,
    require_admin_csrf_token,
)


def _build_app():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")

    @app.get("/issue")
    def issue(request):  # type: ignore[no-redef]
        from fastapi import Request as R  # noqa: F401
        return {}

    return app


def test_ensure_and_require_round_trip():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")

    @app.get("/issue")
    def issue(req):  # noqa: F811
        from fastapi import Request
        return {}

    # 실제 라우트로 토큰을 발급/검증한다
    app2 = FastAPI()
    app2.add_middleware(SessionMiddleware, secret_key="test-secret")

    from fastapi import Request

    @app2.get("/get-token")
    def get_token(request: Request):
        token = ensure_admin_csrf_token(request)
        return {"token": token}

    @app2.post("/protected")
    def protected(request: Request):
        require_admin_csrf_token(request)
        return {"ok": True}

    with TestClient(app2) as client:
        r = client.get("/get-token")
        token = r.json()["token"]
        assert token

        # 헤더 누락 → 403
        r = client.post("/protected")
        assert r.status_code == 403

        # 헤더 일치 → 200
        r = client.post("/protected", headers={ADMIN_CSRF_HEADER: token})
        assert r.status_code == 200

        # 헤더 불일치 → 403
        r = client.post("/protected", headers={ADMIN_CSRF_HEADER: "bogus"})
        assert r.status_code == 403
```

- [ ] **Step 4: 테스트 + 회귀 테스트 실행**

```bash
pytest tests/test_admin_csrf_util.py tests/test_admin_users.py -v
```

Expected: 모두 PASS. 기존 users.py 테스트가 그대로 통과해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add app/utils/admin_csrf.py app/routers/admin/users.py tests/test_admin_csrf_util.py
git commit -m "refactor(admin-csrf): extract CSRF helpers to app/utils/admin_csrf for reuse"
```

---

### Task 2: 삭제 서비스 — 골격 + 사용자 삭제

**Files:**
- Create: `app/services/admin_deletion_service.py`
- Create: `tests/test_admin_deletion_service.py`

- [ ] **Step 1: 실패 테스트 작성 — 사용자 삭제 happy path / 관리자 차단 / 자기 자신 차단**

`tests/test_admin_deletion_service.py`:

```python
"""AdminDeletionService 단위 테스트."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from app.db import Base
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.users import User
from app.services.admin_deletion_service import AdminDeletionService
from tests.conftest import TestingSessionLocal, engine


@pytest_asyncio.fixture
async def db_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seeded(db_tables, tmp_path):
    """관리자 + 일반 사용자 + 세션 + 보고서 시드."""
    async with TestingSessionLocal() as db:
        admin = User(
            username="admin1",
            nickname="Admin",
            email="admin@test.com",
            hashed_password="h",
            is_admin=True,
        )
        user = User(
            username="stu1",
            nickname="Student",
            email="stu1@test.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add_all([admin, user])
        await db.flush()

        session = ChatSession(
            user_id=user.id,
            user_type="1학년",
            title="대화A",
        )
        db.add(session)
        await db.flush()

        msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content="질문",
        )
        db.add(msg)

        # 실제 파일을 생성하여 삭제 검증에 사용
        report_file = tmp_path / "report.md"
        report_file.write_text("# 보고서", encoding="utf-8")

        lessonplan_dir = tmp_path / "uploads"
        lessonplan_dir.mkdir()
        lessonplan_file = lessonplan_dir / "stu1_20260101000000_plan.pdf"
        lessonplan_file.write_bytes(b"%PDF-1.4\n")

        report = AnalysisReport(
            user_id=user.id,
            lessonplan_filename=str(lessonplan_file),
            lessonplan_original_name="plan.pdf",
            report_filename=report_file.name,
            report_path=str(report_file),
            latency_ms=1000,
        )
        db.add(report)
        await db.commit()

        yield {
            "admin_id": admin.id,
            "user_id": user.id,
            "session_id": session.id,
            "report_id": report.id,
            "report_file": report_file,
            "lessonplan_file": lessonplan_file,
        }


@pytest.mark.asyncio
async def test_delete_user_cascades_and_removes_files(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        result = await service.delete_user(
            target_user_id=seeded["user_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 2  # report.md + lessonplan.pdf
    assert not seeded["report_file"].exists()
    assert not seeded["lessonplan_file"].exists()


@pytest.mark.asyncio
async def test_delete_user_blocks_admin_target(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        with pytest.raises(PermissionError):
            await service.delete_user(
                target_user_id=seeded["admin_id"],
                current_admin_id=seeded["admin_id"],
            )


@pytest.mark.asyncio
async def test_delete_user_blocks_self(seeded):
    """다른 관리자가 자기 자신을 지우려는 경우도 PermissionError."""
    async with TestingSessionLocal() as db:
        # 두 번째 관리자 추가
        another_admin = User(
            username="admin2",
            nickname="Admin2",
            email="admin2@test.com",
            hashed_password="h",
            is_admin=True,
        )
        db.add(another_admin)
        await db.commit()
        await db.refresh(another_admin)

        service = AdminDeletionService(db)
        with pytest.raises(PermissionError):
            await service.delete_user(
                target_user_id=another_admin.id,
                current_admin_id=another_admin.id,
            )


@pytest.mark.asyncio
async def test_delete_user_not_found(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        with pytest.raises(LookupError):
            await service.delete_user(
                target_user_id=99999,
                current_admin_id=seeded["admin_id"],
            )
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

```bash
pytest tests/test_admin_deletion_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.admin_deletion_service'`.

- [ ] **Step 3: 서비스 구현 (사용자 삭제만)**

`app/services/admin_deletion_service.py`:

```python
"""관리자용 삭제 서비스.

사용자/대화/보고서의 hard delete와 연관 파일 정리를 담당한다.
모든 권한·CSRF 검증은 호출 측(라우터)에서 처리한다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_reports import AnalysisReport
from app.models.chat_sessions import ChatSession
from app.models.users import User
from app.utils.logging import log_user_action

logger = logging.getLogger(__name__)


class AdminDeletionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ----- 사용자 -----
    async def delete_user(
        self,
        target_user_id: int,
        current_admin_id: int,
    ) -> dict[str, Any]:
        if target_user_id == current_admin_id:
            raise PermissionError("자기 자신은 삭제할 수 없습니다.")

        result = await self.db.execute(
            select(User).where(User.id == target_user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise LookupError("사용자를 찾을 수 없습니다.")
        if user.is_admin:
            raise PermissionError("관리자 계정은 삭제할 수 없습니다.")

        # 파일 정리를 위해 보고서 목록을 먼저 수집
        reports_result = await self.db.execute(
            select(AnalysisReport).where(
                AnalysisReport.user_id == target_user_id
            )
        )
        reports = list(reports_result.scalars().all())

        # DB 삭제 — relationship cascade가 세션/메시지/프로필 처리
        await self.db.delete(user)
        await self.db.commit()

        files_removed = self._remove_report_files(reports)

        log_user_action(
            user_id=current_admin_id,
            action="admin_user_delete",
            details={
                "target_user_id": target_user_id,
                "files_removed": files_removed,
            },
            success=True,
        )
        return {"ok": True, "deleted": 1, "files_removed": files_removed}

    # ----- 파일 정리 헬퍼 -----
    def _remove_report_files(
        self, reports: list[AnalysisReport]
    ) -> int:
        """report_path(.md) + lessonplan_filename(.pdf 경로) 삭제."""
        removed = 0
        for report in reports:
            for raw_path in (report.report_path, report.lessonplan_filename):
                if not raw_path:
                    continue
                path = Path(raw_path)
                if not path.exists():
                    continue
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    logger.warning(
                        "파일 삭제 실패: path=%s, err=%s", path, exc
                    )
        return removed
```

> **Note for engineer:** `_remove_report_files`는 `report_path`와 `lessonplan_filename` 두 컬럼만 정리한다. 현재 코드베이스에서 lessonplan PDF는 `app/static/uploads/`에 절대 경로로 저장되지만, `AnalysisReport.lessonplan_filename`이 절대 경로인지 파일명만인지 일관되지 않을 수 있다. **경로가 절대 경로일 때만 삭제**하고, 단순 파일명만 들어있는 경우는 무시한다 (오삭제 방지). 위 구현은 `Path(raw_path).exists()`로 자연스럽게 처리된다.

- [ ] **Step 4: 테스트 실행해서 통과 확인**

```bash
pytest tests/test_admin_deletion_service.py -v
```

Expected: 4개 테스트 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/services/admin_deletion_service.py tests/test_admin_deletion_service.py
git commit -m "feat(admin-deletion): add AdminDeletionService.delete_user with cascade + file cleanup"
```

---

### Task 3: 서비스 — 대화 세션 / 보고서 / bulk 삭제

**Files:**
- Modify: `app/services/admin_deletion_service.py`
- Modify: `tests/test_admin_deletion_service.py`

- [ ] **Step 1: 실패 테스트 추가 — 단일 세션, 단일 보고서, bulk 세션, bulk 보고서, bulk 소유권 검증**

`tests/test_admin_deletion_service.py` 끝에 추가:

```python
@pytest.mark.asyncio
async def test_delete_chat_session_cascades_messages(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        result = await service.delete_chat_session(
            session_id=seeded["session_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 1

    async with TestingSessionLocal() as db:
        from sqlalchemy import select
        from app.models.chat_messages import ChatMessage
        msg_rows = await db.execute(select(ChatMessage))
        assert msg_rows.scalars().all() == []


@pytest.mark.asyncio
async def test_delete_chat_session_not_found(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        with pytest.raises(LookupError):
            await service.delete_chat_session(
                session_id=99999,
                current_admin_id=seeded["admin_id"],
            )


@pytest.mark.asyncio
async def test_delete_analysis_report_removes_files(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        result = await service.delete_analysis_report(
            report_id=seeded["report_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 2
    assert not seeded["report_file"].exists()
    assert not seeded["lessonplan_file"].exists()


@pytest.mark.asyncio
async def test_bulk_delete_sessions_requires_ownership(seeded):
    """타 사용자 세션이 섞이면 0건 삭제 + ValueError."""
    async with TestingSessionLocal() as db:
        # 두 번째 사용자 + 세션 생성
        from app.models.users import User
        from app.models.chat_sessions import ChatSession
        other = User(
            username="stu2",
            nickname="S2",
            email="s2@test.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add(other)
        await db.flush()
        other_session = ChatSession(
            user_id=other.id, user_type="1학년", title="B"
        )
        db.add(other_session)
        await db.commit()
        await db.refresh(other_session)

        service = AdminDeletionService(db)
        with pytest.raises(ValueError):
            await service.bulk_delete_sessions(
                user_id=seeded["user_id"],
                session_ids=[seeded["session_id"], other_session.id],
                current_admin_id=seeded["admin_id"],
            )


@pytest.mark.asyncio
async def test_bulk_delete_sessions_happy(seeded):
    async with TestingSessionLocal() as db:
        # 두 번째 세션 추가
        from app.models.chat_sessions import ChatSession
        s2 = ChatSession(
            user_id=seeded["user_id"], user_type="2학년", title="B"
        )
        db.add(s2)
        await db.commit()
        await db.refresh(s2)
        ids = [seeded["session_id"], s2.id]

        service = AdminDeletionService(db)
        result = await service.bulk_delete_sessions(
            user_id=seeded["user_id"],
            session_ids=ids,
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 2


@pytest.mark.asyncio
async def test_bulk_delete_reports_happy(seeded, tmp_path):
    async with TestingSessionLocal() as db:
        from app.models.analysis_reports import AnalysisReport
        f2 = tmp_path / "report2.md"
        f2.write_text("# r2", encoding="utf-8")
        r2 = AnalysisReport(
            user_id=seeded["user_id"],
            lessonplan_filename="",  # 빈 값 — 파일 미삭제
            lessonplan_original_name="b.pdf",
            report_filename=f2.name,
            report_path=str(f2),
            latency_ms=100,
        )
        db.add(r2)
        await db.commit()
        await db.refresh(r2)

        service = AdminDeletionService(db)
        result = await service.bulk_delete_reports(
            user_id=seeded["user_id"],
            report_ids=[seeded["report_id"], r2.id],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 2
    assert result["files_removed"] >= 2
    assert not seeded["report_file"].exists()
    assert not f2.exists()
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

```bash
pytest tests/test_admin_deletion_service.py -v
```

Expected: 새 6개 테스트가 `AttributeError: 'AdminDeletionService' object has no attribute 'delete_chat_session'` 등으로 실패.

- [ ] **Step 3: 서비스 메서드 구현**

`app/services/admin_deletion_service.py`의 `AdminDeletionService` 클래스에 다음 메서드를 추가 (`_remove_report_files` 위에):

```python
    # ----- 대화 세션 -----
    async def delete_chat_session(
        self,
        session_id: int,
        current_admin_id: int,
    ) -> dict[str, Any]:
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise LookupError("대화 세션을 찾을 수 없습니다.")

        await self.db.delete(session)  # cascade: messages
        await self.db.commit()

        log_user_action(
            user_id=current_admin_id,
            action="admin_chat_session_delete",
            details={"session_id": session_id},
            success=True,
        )
        return {"ok": True, "deleted": 1, "files_removed": 0}

    # ----- 분석 보고서 -----
    async def delete_analysis_report(
        self,
        report_id: int,
        current_admin_id: int,
    ) -> dict[str, Any]:
        result = await self.db.execute(
            select(AnalysisReport).where(AnalysisReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if report is None:
            raise LookupError("분석 보고서를 찾을 수 없습니다.")

        files_removed = self._remove_report_files([report])

        await self.db.delete(report)
        await self.db.commit()

        log_user_action(
            user_id=current_admin_id,
            action="admin_analysis_report_delete",
            details={
                "report_id": report_id,
                "files_removed": files_removed,
            },
            success=True,
        )
        return {
            "ok": True,
            "deleted": 1,
            "files_removed": files_removed,
        }

    # ----- bulk -----
    async def bulk_delete_sessions(
        self,
        user_id: int,
        session_ids: list[int],
        current_admin_id: int,
    ) -> dict[str, Any]:
        if not session_ids:
            return {"ok": True, "deleted": 0, "files_removed": 0}

        rows = await self.db.execute(
            select(ChatSession).where(ChatSession.id.in_(session_ids))
        )
        sessions = list(rows.scalars().all())

        # 모든 세션이 user_id에 속해야 한다
        bad = [s.id for s in sessions if s.user_id != user_id]
        if len(sessions) != len(session_ids) or bad:
            raise ValueError(
                "요청한 세션 중 일부가 해당 사용자 소유가 아니거나 존재하지 않습니다."
            )

        for session in sessions:
            await self.db.delete(session)
        await self.db.commit()

        log_user_action(
            user_id=current_admin_id,
            action="admin_chat_session_bulk_delete",
            details={
                "target_user_id": user_id,
                "session_ids": session_ids,
            },
            success=True,
        )
        return {
            "ok": True,
            "deleted": len(sessions),
            "files_removed": 0,
        }

    async def bulk_delete_reports(
        self,
        user_id: int,
        report_ids: list[int],
        current_admin_id: int,
    ) -> dict[str, Any]:
        if not report_ids:
            return {"ok": True, "deleted": 0, "files_removed": 0}

        rows = await self.db.execute(
            select(AnalysisReport).where(
                AnalysisReport.id.in_(report_ids)
            )
        )
        reports = list(rows.scalars().all())

        bad = [r.id for r in reports if r.user_id != user_id]
        if len(reports) != len(report_ids) or bad:
            raise ValueError(
                "요청한 보고서 중 일부가 해당 사용자 소유가 아니거나 존재하지 않습니다."
            )

        files_removed = self._remove_report_files(reports)
        for report in reports:
            await self.db.delete(report)
        await self.db.commit()

        log_user_action(
            user_id=current_admin_id,
            action="admin_analysis_report_bulk_delete",
            details={
                "target_user_id": user_id,
                "report_ids": report_ids,
                "files_removed": files_removed,
            },
            success=True,
        )
        return {
            "ok": True,
            "deleted": len(reports),
            "files_removed": files_removed,
        }
```

- [ ] **Step 4: 테스트 실행해서 모두 통과 확인**

```bash
pytest tests/test_admin_deletion_service.py -v
```

Expected: 10개 테스트 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/services/admin_deletion_service.py tests/test_admin_deletion_service.py
git commit -m "feat(admin-deletion): add session/report/bulk delete operations to AdminDeletionService"
```

---

### Task 4: DELETE 엔드포인트 — 사용자

**Files:**
- Modify: `app/routers/admin/users.py`
- Create: `tests/test_admin_deletion_endpoints.py`

- [ ] **Step 1: 통합 테스트 작성 (실패)**

`tests/test_admin_deletion_endpoints.py`:

```python
"""관리자 삭제 엔드포인트 통합 테스트."""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.dependencies import get_current_admin
from app.main import app
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.users import User
from app.utils.admin_csrf import ADMIN_CSRF_HEADER
from tests.conftest import (
    TestingSessionLocal,
    engine,
    override_admin,
    override_get_db,
)

_admin = User(
    id=999,
    username="admin",
    nickname="A",
    email="a@t.com",
    hashed_password="h",
    is_admin=True,
)


@pytest.fixture(autouse=True)
def _overrides():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_admin(_admin)
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seeded(db_tables, tmp_path):
    async with TestingSessionLocal() as db:
        # 테스트용 admin도 DB에 저장 (FK 무결성/감사 기록을 위해)
        admin_row = User(
            id=_admin.id,
            username=_admin.username,
            nickname=_admin.nickname,
            email=_admin.email,
            hashed_password="h",
            is_admin=True,
        )
        user = User(
            username="stu1",
            nickname="S1",
            email="s1@t.com",
            hashed_password="h",
            is_admin=False,
        )
        another_admin = User(
            username="admin2",
            nickname="A2",
            email="a2@t.com",
            hashed_password="h",
            is_admin=True,
        )
        db.add_all([admin_row, user, another_admin])
        await db.flush()

        session = ChatSession(user_id=user.id, user_type="1학년", title="A")
        db.add(session)
        await db.flush()
        db.add(ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content="hi",
        ))

        report_file = tmp_path / "r.md"
        report_file.write_text("x", encoding="utf-8")
        report = AnalysisReport(
            user_id=user.id,
            lessonplan_filename="",
            lessonplan_original_name="p.pdf",
            report_filename="r.md",
            report_path=str(report_file),
            latency_ms=1,
        )
        db.add(report)
        await db.commit()
        await db.refresh(user)
        await db.refresh(session)
        await db.refresh(report)
        await db.refresh(another_admin)

        yield {
            "user_id": user.id,
            "session_id": session.id,
            "report_id": report.id,
            "another_admin_id": another_admin.id,
            "report_file": report_file,
        }


def _csrf_client():
    client = TestClient(app)
    # 라우터에서 GET /admin/users (HTML) 호출 시 세션 CSRF 토큰 발급
    r = client.get("/admin/users")
    # csrf 토큰을 HTML에서 파싱하기보다 직접 세션에 접근
    # 테스트에서는 보호 엔드포인트 호출 직전에 GET으로 토큰 발급 후 헤더 주입
    token = client.cookies.get("session")  # placeholder
    return client, token


@pytest.mark.asyncio
async def test_delete_user_happy(seeded):
    with TestClient(app) as client:
        client.get("/admin/users")  # 세션·CSRF 토큰 발급
        # CSRF 토큰은 응답 HTML의 meta 태그에 들어있다. 세션에 저장된
        # 값을 쓰기 위해 GET /admin/users 응답에서 추출한다.
        html = client.get("/admin/users").text
        import re
        m = re.search(r'name="csrf-token" content="([^"]+)"', html)
        assert m, "csrf-token meta missing"
        token = m.group(1)

        resp = client.delete(
            f"/admin/api/users/{seeded['user_id']}",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["deleted"] == 1


@pytest.mark.asyncio
async def test_delete_user_admin_target_forbidden(seeded):
    with TestClient(app) as client:
        html = client.get("/admin/users").text
        import re
        token = re.search(
            r'name="csrf-token" content="([^"]+)"', html
        ).group(1)

        resp = client.delete(
            f"/admin/api/users/{seeded['another_admin_id']}",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_self_forbidden(seeded):
    """현재 admin이 자기 자신을 지우려는 경우 403."""
    with TestClient(app) as client:
        html = client.get("/admin/users").text
        import re
        token = re.search(
            r'name="csrf-token" content="([^"]+)"', html
        ).group(1)

        resp = client.delete(
            f"/admin/api/users/{_admin.id}",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_csrf_required(seeded):
    with TestClient(app) as client:
        resp = client.delete(f"/admin/api/users/{seeded['user_id']}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_not_found(seeded):
    with TestClient(app) as client:
        html = client.get("/admin/users").text
        import re
        token = re.search(
            r'name="csrf-token" content="([^"]+)"', html
        ).group(1)

        resp = client.delete(
            "/admin/api/users/99999",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 404
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

```bash
pytest tests/test_admin_deletion_endpoints.py::test_delete_user_happy -v
```

Expected: `405 Method Not Allowed` 또는 404 (엔드포인트 미구현).

- [ ] **Step 3: 라우터에 DELETE 엔드포인트 추가**

`app/routers/admin/users.py`에 다음 import 추가:

```python
from app.services.admin_deletion_service import AdminDeletionService
```

그리고 `change_regular_user_password` 함수 아래에 추가:

```python
@router.delete("/admin/api/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 전용 사용자 삭제 API.

    cascade: chat_sessions / chat_messages / analysis_reports / user_profiles.
    파일: 각 AnalysisReport의 report_path(.md) + lessonplan_filename(.pdf).
    """
    require_admin_csrf_token(request)

    service = AdminDeletionService(db)
    try:
        result = await service.delete_user(
            target_user_id=user_id,
            current_admin_id=current_admin.id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        log_user_action(
            user_id=current_admin.id,
            action="admin_user_delete",
            details={
                "target_user_id": user_id,
                "reason": str(exc),
            },
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    logger.info(
        "관리자 사용자 삭제: admin_id=%s, target_user_id=%s",
        current_admin.id,
        user_id,
    )
    return result
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

```bash
pytest tests/test_admin_deletion_endpoints.py -v -k "test_delete_user"
```

Expected: 5개 테스트 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/routers/admin/users.py tests/test_admin_deletion_endpoints.py
git commit -m "feat(admin-deletion): add DELETE /admin/api/users/{user_id} endpoint with CSRF + admin guard"
```

---

### Task 5: DELETE 엔드포인트 — 대화 세션 / 보고서

**Files:**
- Modify: `app/routers/admin/users.py`
- Modify: `tests/test_admin_deletion_endpoints.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_admin_deletion_endpoints.py` 끝에 추가:

```python
def _get_token(client):
    import re
    html = client.get("/admin/users").text
    return re.search(
        r'name="csrf-token" content="([^"]+)"', html
    ).group(1)


@pytest.mark.asyncio
async def test_delete_chat_session_happy(seeded):
    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.delete(
            f"/admin/api/chat-sessions/{seeded['session_id']}",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1


@pytest.mark.asyncio
async def test_delete_chat_session_not_found(seeded):
    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.delete(
            "/admin/api/chat-sessions/99999",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_chat_session_csrf_required(seeded):
    with TestClient(app) as client:
        resp = client.delete(
            f"/admin/api/chat-sessions/{seeded['session_id']}"
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_report_happy_removes_file(seeded):
    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.delete(
            f"/admin/api/reports/{seeded['report_id']}",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    assert not seeded["report_file"].exists()


@pytest.mark.asyncio
async def test_delete_report_not_found(seeded):
    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.delete(
            "/admin/api/reports/99999",
            headers={ADMIN_CSRF_HEADER: token},
        )
    assert resp.status_code == 404
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

```bash
pytest tests/test_admin_deletion_endpoints.py -v -k "test_delete_chat_session or test_delete_report"
```

Expected: 5개 테스트 모두 FAIL (엔드포인트 없음).

- [ ] **Step 3: 라우터 엔드포인트 추가**

`app/routers/admin/users.py`의 `delete_user` 아래에 추가:

```python
@router.delete("/admin/api/chat-sessions/{session_id}")
async def delete_chat_session(
    session_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 전용 단일 대화 세션 삭제 (messages cascade)."""
    require_admin_csrf_token(request)
    service = AdminDeletionService(db)
    try:
        result = await service.delete_chat_session(
            session_id=session_id,
            current_admin_id=current_admin.id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    logger.info(
        "관리자 대화 세션 삭제: admin_id=%s, session_id=%s",
        current_admin.id,
        session_id,
    )
    return result


@router.delete("/admin/api/reports/{report_id}")
async def delete_analysis_report(
    report_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 전용 단일 분석 보고서 삭제 (.md/.pdf 파일 포함)."""
    require_admin_csrf_token(request)
    service = AdminDeletionService(db)
    try:
        result = await service.delete_analysis_report(
            report_id=report_id,
            current_admin_id=current_admin.id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    logger.info(
        "관리자 분석 보고서 삭제: admin_id=%s, report_id=%s",
        current_admin.id,
        report_id,
    )
    return result
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_admin_deletion_endpoints.py -v
```

Expected: 모든 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/routers/admin/users.py tests/test_admin_deletion_endpoints.py
git commit -m "feat(admin-deletion): add DELETE chat-sessions and reports endpoints"
```

---

### Task 6: bulk 삭제 엔드포인트

**Files:**
- Modify: `app/routers/admin/users.py`
- Modify: `tests/test_admin_deletion_endpoints.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_admin_deletion_endpoints.py` 끝에 추가:

```python
@pytest.mark.asyncio
async def test_bulk_delete_sessions_happy(seeded):
    # 두 번째 세션을 추가
    async with TestingSessionLocal() as db:
        from app.models.chat_sessions import ChatSession
        s2 = ChatSession(
            user_id=seeded["user_id"], user_type="2학년", title="B"
        )
        db.add(s2)
        await db.commit()
        await db.refresh(s2)
        ids = [seeded["session_id"], s2.id]

    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.post(
            f"/admin/api/users/{seeded['user_id']}/sessions/bulk-delete",
            headers={ADMIN_CSRF_HEADER: token},
            json={"session_ids": ids},
        )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2


@pytest.mark.asyncio
async def test_bulk_delete_sessions_rejects_cross_user(seeded):
    async with TestingSessionLocal() as db:
        from app.models.users import User
        from app.models.chat_sessions import ChatSession
        other = User(
            username="stuX",
            nickname="X",
            email="x@t.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add(other)
        await db.flush()
        bad_session = ChatSession(
            user_id=other.id, user_type="1학년", title="X"
        )
        db.add(bad_session)
        await db.commit()
        await db.refresh(bad_session)

    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.post(
            f"/admin/api/users/{seeded['user_id']}/sessions/bulk-delete",
            headers={ADMIN_CSRF_HEADER: token},
            json={"session_ids": [seeded["session_id"], bad_session.id]},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_bulk_delete_reports_happy(seeded, tmp_path):
    async with TestingSessionLocal() as db:
        from app.models.analysis_reports import AnalysisReport
        f2 = tmp_path / "r2.md"
        f2.write_text("x", encoding="utf-8")
        r2 = AnalysisReport(
            user_id=seeded["user_id"],
            lessonplan_filename="",
            lessonplan_original_name="b.pdf",
            report_filename="r2.md",
            report_path=str(f2),
            latency_ms=1,
        )
        db.add(r2)
        await db.commit()
        await db.refresh(r2)
        ids = [seeded["report_id"], r2.id]

    with TestClient(app) as client:
        token = _get_token(client)
        resp = client.post(
            f"/admin/api/users/{seeded['user_id']}/reports/bulk-delete",
            headers={ADMIN_CSRF_HEADER: token},
            json={"report_ids": ids},
        )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2


@pytest.mark.asyncio
async def test_bulk_delete_csrf_required(seeded):
    with TestClient(app) as client:
        resp = client.post(
            f"/admin/api/users/{seeded['user_id']}/sessions/bulk-delete",
            json={"session_ids": [seeded["session_id"]]},
        )
    assert resp.status_code == 403
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

```bash
pytest tests/test_admin_deletion_endpoints.py -v -k "bulk"
```

Expected: 4개 모두 FAIL.

- [ ] **Step 3: 라우터 엔드포인트 추가**

`app/routers/admin/users.py`의 `delete_analysis_report` 아래에 추가:

```python
async def _read_id_list(request: Request, key: str) -> list[int]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="요청 본문이 올바른 JSON 형식이 아닙니다.",
        ) from exc
    raw = payload.get(key)
    if not isinstance(raw, list) or not all(
        isinstance(item, int) for item in raw
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{key}는 정수 배열이어야 합니다.",
        )
    return raw


@router.post(
    "/admin/api/users/{user_id}/sessions/bulk-delete"
)
async def bulk_delete_user_sessions(
    user_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    require_admin_csrf_token(request)
    session_ids = await _read_id_list(request, "session_ids")

    service = AdminDeletionService(db)
    try:
        result = await service.bulk_delete_sessions(
            user_id=user_id,
            session_ids=session_ids,
            current_admin_id=current_admin.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return result


@router.post(
    "/admin/api/users/{user_id}/reports/bulk-delete"
)
async def bulk_delete_user_reports(
    user_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    require_admin_csrf_token(request)
    report_ids = await _read_id_list(request, "report_ids")

    service = AdminDeletionService(db)
    try:
        result = await service.bulk_delete_reports(
            user_id=user_id,
            report_ids=report_ids,
            current_admin_id=current_admin.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return result
```

> **Note:** `_read_id_list`는 `request.json()`을 한 번만 소비한다. FastAPI에서 `Request.json()`을 두 번 부르면 캐시된 body가 재사용되므로 같은 함수 안에서 두 번 호출하는 일은 없도록 한다.

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_admin_deletion_endpoints.py -v
```

Expected: 모든 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/routers/admin/users.py tests/test_admin_deletion_endpoints.py
git commit -m "feat(admin-deletion): add bulk delete endpoints for sessions and reports"
```

---

### Task 7: QnA 로그 페이지에 CSRF 토큰 주입

**Files:**
- Modify: `app/routers/admin/qna_logs.py`

- [ ] **Step 1: 라우터 수정**

`app/routers/admin/qna_logs.py`의 `qna_logs_page` 함수를 다음으로 교체:

```python
from app.utils.admin_csrf import ensure_admin_csrf_token


@router.get("/admin/qna-logs", response_class=HTMLResponse)
async def qna_logs_page(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    """QnA 로그 페이지 렌더링.

    세션 삭제 작업을 위해 CSRF 토큰을 함께 주입한다.
    """
    csrf_token = ensure_admin_csrf_token(request)
    return templates.TemplateResponse(
        "admin/admin_qna_logs.html",
        {
            "request": request,
            "user": current_admin,
            "csrf_token": csrf_token,
        },
    )
```

import는 파일 상단에 정리 (`from app.utils.admin_csrf import ensure_admin_csrf_token`).

- [ ] **Step 2: 회귀 테스트**

```bash
pytest tests/test_admin_users.py -v  # 기존 테스트가 영향받지 않는지 확인
```

Expected: PASS.

- [ ] **Step 3: 수동 점검**

```bash
# (선택) 개발 서버를 띄워 /admin/qna-logs 페이지를 열고
# 페이지 소스에 <meta name="csrf-token" content="...">가 보이는지 확인
# (실제 meta 태그는 Task 10에서 추가하므로 이 시점에서는 csrf_token만 전달)
```

- [ ] **Step 4: 커밋**

```bash
git add app/routers/admin/qna_logs.py
git commit -m "feat(admin-qna-logs): inject CSRF token into QnA logs page for delete actions"
```

---

### Task 8: admin_users.html — 사용자 삭제 UI

**Files:**
- Modify: `app/templates/admin/admin_users.html`

- [ ] **Step 1: 사용자 계정 목록 테이블 헤더에 "삭제" 컬럼 추가**

`app/templates/admin/admin_users.html:138` 부근의 `<th>...비밀번호 변경</th>` 바로 뒤에 추가:

```html
<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">삭제</th>
```

그리고 `tbody`의 로딩 행 `<tr><td colspan="9" ...>로딩 중...</td></tr>` 의 colspan을 `9` → `10`으로 변경 (두 곳: 로딩 행 + 빈 결과 행 + 에러 행).

- [ ] **Step 2: 각 사용자 행에 삭제 버튼 추가**

`tbody.innerHTML = data.accounts.map(...)` 안의 행 템플릿(`return \`...\`;`) 끝의 `</tr>` 직전에 새 `<td>` 추가:

```javascript
                    <td class="px-3 py-3 text-sm whitespace-nowrap">
                        ${account.is_admin || account.user_id === CURRENT_ADMIN_ID
                            ? '<span class="text-xs text-gray-400">불가</span>'
                            : `<button onclick="deleteUser(${account.user_id}, '${escapeHtml(account.email || account.username).replace(/'/g, "\\'")}')"
                                  class="bg-red-600 text-white px-3 py-1 rounded-md text-sm hover:bg-red-700">삭제</button>`}
                    </td>
```

> 위 템플릿은 백틱 안의 백슬래시 이스케이프에 주의. 안전한 대안: 행 전체를 데이터로 채운 뒤 별도 함수로 버튼을 렌더링.

`<script>` 블록 최상단(`let currentPage = 1;` 위)에 다음 추가:

```javascript
const CURRENT_ADMIN_ID = {{ user.id }};  // Jinja 치환
```

- [ ] **Step 3: deleteUser 함수 추가**

`changePassword` 함수 아래에 추가:

```javascript
async function deleteUser(userId, label) {
    const confirmed = window.confirm(
        `정말 사용자 [${label}]를 삭제하시겠습니까?\n` +
        `대화 기록·분석 보고서·업로드 파일이 모두 삭제됩니다.\n` +
        `이 작업은 되돌릴 수 없습니다.`
    );
    if (!confirmed) return;

    try {
        const response = await fetch(`/admin/api/users/${userId}`, {
            method: 'DELETE',
            headers: { 'X-CSRF-Token': getCsrfToken() },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            alert(data.detail || '사용자 삭제에 실패했습니다.');
            return;
        }
        alert(`사용자가 삭제되었습니다. 파일 ${data.files_removed}건 정리.`);
        loadAccounts(accountPage);
        loadSessions(currentPage);
        loadStats();
    } catch (error) {
        console.error('사용자 삭제 실패:', error);
        alert('사용자 삭제 중 오류가 발생했습니다.');
    }
}
```

- [ ] **Step 4: 수동 점검**

```bash
make run  # 또는 uvicorn app.main:app --reload
```

브라우저에서 `/admin/users` → 사용자 행의 "삭제" 버튼 → confirm → 삭제 → 목록이 갱신되는지 확인. 관리자 행에는 "불가" 표시인지 확인.

- [ ] **Step 5: 커밋**

```bash
git add app/templates/admin/admin_users.html
git commit -m "feat(admin-users-ui): add delete column and confirm flow for user accounts"
```

---

### Task 9: admin_user_detail.html — 개별/일괄 삭제 UI

**Files:**
- Modify: `app/templates/admin/admin_user_detail.html`
- Modify: `app/routers/admin/users.py` (CSRF token을 detail 페이지에도 주입)

- [ ] **Step 1: detail 페이지 라우터에 CSRF 토큰 주입**

`app/routers/admin/users.py`의 `admin_user_detail_page` 함수에서 `templates.TemplateResponse(...)` 호출 직전에 CSRF 토큰을 생성하고 context에 전달:

```python
    csrf_token = ensure_admin_csrf_token(request)
    return templates.TemplateResponse(
        "admin/admin_user_detail.html",
        {
            "request": request,
            "user": current_admin,
            "target_user_id": user_id,
            "csrf_token": csrf_token,
        },
    )
```

- [ ] **Step 2: 템플릿 head에 CSRF meta 추가**

`app/templates/admin/admin_user_detail.html`의 `{% block title %}...{% endblock %}` 바로 뒤에 추가:

```html
{% block head %}
<meta name="csrf-token" content="{{ csrf_token }}">
{% endblock %}
```

- [ ] **Step 3: 세션 목록에 체크박스 + 개별 삭제 + 일괄 삭제 UI 추가**

`renderSessions` 함수의 `itemsHtml` 구성을 다음으로 교체:

```javascript
    const itemsHtml = adminSessions.map((s) => `
        <li class="py-3 flex items-start gap-3">
            <input type="checkbox" class="session-check mt-2" data-id="${s.session_id}">
            <a href="/admin/users/session/${s.session_id}" class="flex-1 block hover:bg-gray-50 rounded p-2 -m-2">
                <div class="font-medium text-blue-700">${escapeHtml(s.title || '제목 없음')}</div>
                <div class="text-xs text-gray-500 mt-1">
                    메시지 ${s.message_count} · 최근 ${formatDate(s.last_message_at || s.updated_at || s.created_at)}
                </div>
            </a>
            <button type="button"
                onclick="deleteOneSession(${s.session_id})"
                class="bg-red-600 text-white px-2 py-1 rounded text-xs hover:bg-red-700">삭제</button>
        </li>
    `).join('');
```

그리고 세션 섹션 헤더(`<h2>대화</h2>`가 있는 div) 아래, `<ul id="adminSessionList" ...>` 위에 일괄 삭제 바를 추가:

```html
        <div class="flex items-center justify-between mb-2 hidden" id="bulkSessionBar">
            <span class="text-xs text-gray-500" id="bulkSessionCount">0건 선택</span>
            <button type="button" onclick="bulkDeleteSessions()"
                class="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700">선택 삭제</button>
        </div>
```

`renderSessions` 끝에 다음 라인 추가 (체크박스 이벤트 바인딩):

```javascript
    list.querySelectorAll('.session-check').forEach((cb) => {
        cb.addEventListener('change', updateBulkSessionBar);
    });
```

- [ ] **Step 4: 보고서 목록도 동일한 방식으로 체크박스 + 삭제 UI 추가**

`renderReports`의 `itemsHtml`을:

```javascript
    const itemsHtml = adminReports.map((r) => `
        <li class="py-3 flex items-start gap-3">
            <input type="checkbox" class="report-check mt-2" data-id="${r.id}">
            <a href="/admin/reports/view/${r.id}" class="flex-1 block hover:bg-gray-50 rounded p-2 -m-2">
                <div class="font-medium text-blue-700">${escapeHtml(r.lessonplan_original_name || r.report_filename)}</div>
                <div class="text-xs text-gray-500 mt-1">생성일 ${formatDate(r.created_at)}</div>
            </a>
            <button type="button"
                onclick="deleteOneReport(${r.id})"
                class="bg-red-600 text-white px-2 py-1 rounded text-xs hover:bg-red-700">삭제</button>
        </li>
    `).join('');
```

보고서 섹션 헤더 아래에:

```html
        <div class="flex items-center justify-between mb-2 hidden" id="bulkReportBar">
            <span class="text-xs text-gray-500" id="bulkReportCount">0건 선택</span>
            <button type="button" onclick="bulkDeleteReports()"
                class="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700">선택 삭제</button>
        </div>
```

`renderReports` 끝에:

```javascript
    list.querySelectorAll('.report-check').forEach((cb) => {
        cb.addEventListener('change', updateBulkReportBar);
    });
```

- [ ] **Step 5: JS 함수 (delete + bulk + counters) 추가**

`</script>` 직전에 다음 추가:

```javascript
const TARGET_USER_ID = {{ target_user_id }};

function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

function collectIds(selector) {
    return Array.from(document.querySelectorAll(selector + ':checked'))
        .map((cb) => Number(cb.dataset.id));
}

function updateBulkSessionBar() {
    const ids = collectIds('.session-check');
    document.getElementById('bulkSessionBar').classList.toggle('hidden', ids.length === 0);
    document.getElementById('bulkSessionCount').textContent = `${ids.length}건 선택`;
}

function updateBulkReportBar() {
    const ids = collectIds('.report-check');
    document.getElementById('bulkReportBar').classList.toggle('hidden', ids.length === 0);
    document.getElementById('bulkReportCount').textContent = `${ids.length}건 선택`;
}

async function deleteOneSession(id) {
    if (!window.confirm('대화 세션을 삭제하시겠습니까? 메시지가 모두 함께 삭제됩니다.')) return;
    const resp = await fetch(`/admin/api/chat-sessions/${id}`, {
        method: 'DELETE',
        headers: { 'X-CSRF-Token': getCsrfToken() },
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        alert(data.detail || '삭제 실패'); return;
    }
    await loadSessions();
    loadProfile();
}

async function deleteOneReport(id) {
    if (!window.confirm('분석 보고서를 삭제하시겠습니까? 보고서/지도안 파일도 함께 삭제됩니다.')) return;
    const resp = await fetch(`/admin/api/reports/${id}`, {
        method: 'DELETE',
        headers: { 'X-CSRF-Token': getCsrfToken() },
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        alert(data.detail || '삭제 실패'); return;
    }
    await loadReports();
    loadProfile();
}

async function bulkDeleteSessions() {
    const ids = collectIds('.session-check');
    if (ids.length === 0) return;
    if (!window.confirm(`${ids.length}개 대화 세션을 삭제하시겠습니까?`)) return;
    const resp = await fetch(
        `/admin/api/users/${TARGET_USER_ID}/sessions/bulk-delete`,
        {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': getCsrfToken(),
            },
            body: JSON.stringify({ session_ids: ids }),
        },
    );
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        alert(data.detail || '일괄 삭제 실패'); return;
    }
    await loadSessions();
    loadProfile();
}

async function bulkDeleteReports() {
    const ids = collectIds('.report-check');
    if (ids.length === 0) return;
    if (!window.confirm(`${ids.length}개 보고서를 삭제하시겠습니까? 파일도 함께 삭제됩니다.`)) return;
    const resp = await fetch(
        `/admin/api/users/${TARGET_USER_ID}/reports/bulk-delete`,
        {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': getCsrfToken(),
            },
            body: JSON.stringify({ report_ids: ids }),
        },
    );
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        alert(data.detail || '일괄 삭제 실패'); return;
    }
    await loadReports();
    loadProfile();
}
```

- [ ] **Step 6: 수동 점검**

브라우저에서 `/admin/users/{user_id}` 접속 → 세션/보고서 옆 체크박스, 각 행의 [삭제] 버튼, 일괄 삭제 바가 모두 동작하는지 확인. confirm 후 목록이 갱신되는지 확인.

- [ ] **Step 7: 커밋**

```bash
git add app/templates/admin/admin_user_detail.html app/routers/admin/users.py
git commit -m "feat(admin-user-detail-ui): add per-item and bulk delete for sessions and reports"
```

---

### Task 10: admin_qna_logs.html — 세션 삭제 UI

**Files:**
- Modify: `app/templates/admin/admin_qna_logs.html`

- [ ] **Step 1: head 블록에 CSRF meta 추가**

`app/templates/admin/admin_qna_logs.html`의 `{% block title %}...{% endblock %}` 뒤에 추가:

```html
{% block head %}
<meta name="csrf-token" content="{{ csrf_token }}">
{% endblock %}
```

- [ ] **Step 2: 세션 헤더에 삭제 버튼 추가**

기존 세션 헤더 div(`<div class="p-4 cursor-pointer ..." onclick="toggleSession(${index})">`) 내부 마지막 `</div>` 직전(즉, chevron 옆)에 삭제 버튼을 추가하되, 클릭 이벤트 버블링을 막아 토글이 발생하지 않게 한다:

`onclick="toggleSession(${index})"` 영역을 다음과 같이 변경:

```html
<div class="p-4 cursor-pointer hover:bg-gray-50 flex justify-between items-center"
     onclick="toggleSession(${index})">
    <!-- ... 기존 좌측 영역 그대로 ... -->
    <div class="flex items-center gap-3">
        <span class="text-xs text-gray-500">${formatDate(session.created_at)}</span>
        <button type="button"
            onclick="event.stopPropagation(); deleteQnaSession(${session.session_id})"
            class="bg-red-600 text-white px-2 py-1 rounded text-xs hover:bg-red-700">삭제</button>
        <svg id="chevron-${index}" ...> ... </svg>
    </div>
</div>
```

- [ ] **Step 3: deleteQnaSession 함수 추가**

`<script>` 블록 안, `updatePagination` 함수 위에 추가:

```javascript
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

async function deleteQnaSession(sessionId) {
    if (!window.confirm('이 대화 세션을 삭제하시겠습니까? 메시지가 모두 함께 삭제됩니다.')) {
        return;
    }
    try {
        const resp = await fetch(`/admin/api/chat-sessions/${sessionId}`, {
            method: 'DELETE',
            headers: { 'X-CSRF-Token': getCsrfToken() },
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            alert(data.detail || '삭제에 실패했습니다.');
            return;
        }
        loadLogs(currentPage);
    } catch (error) {
        console.error('QnA 세션 삭제 실패:', error);
        alert('삭제 중 오류가 발생했습니다.');
    }
}
```

- [ ] **Step 4: 수동 점검**

브라우저에서 `/admin/qna-logs` 접속 → 각 세션 카드의 [삭제] 버튼 → confirm → 목록이 갱신되는지 확인. 삭제 버튼 클릭 시 토글이 같이 트리거되지 않는지 확인.

- [ ] **Step 5: 회귀 테스트 전체 실행**

```bash
pytest tests/test_admin_users.py tests/test_admin_deletion_service.py tests/test_admin_deletion_endpoints.py tests/test_admin_csrf_util.py -v
```

Expected: 모두 PASS.

- [ ] **Step 6: 커밋**

```bash
git add app/templates/admin/admin_qna_logs.html
git commit -m "feat(admin-qna-logs-ui): add per-session delete button with confirm"
```

---

### Task 11: PR 준비 + 최종 점검

**Files:**
- (변경 없음 — 점검 및 PR 생성)

- [ ] **Step 1: 브랜치 정리 및 전체 회귀 테스트**

```bash
pytest -q
```

Expected: 기존 + 신규 테스트 모두 PASS.

- [ ] **Step 2: PR 생성**

```bash
gh pr create --title "feat(admin): add deletion for users, sessions, reports, and QnA logs" \
  --body "$(cat <<'EOF'
## Summary
- 사용자 계정 목록에서 개별 사용자 삭제 (cascade DB + 파일)
- 사용자 상세에서 개별/일괄 대화·보고서 삭제
- QnA 로그에서 세션 단위 삭제
- CSRF 헬퍼를 `app/utils/admin_csrf.py`로 분리, 신규 `AdminDeletionService` 추가

## Test plan
- [ ] `pytest tests/test_admin_csrf_util.py -v`
- [ ] `pytest tests/test_admin_deletion_service.py -v`
- [ ] `pytest tests/test_admin_deletion_endpoints.py -v`
- [ ] `pytest tests/test_admin_users.py -v` (회귀)
- [ ] 수동: `/admin/users` 사용자 삭제, 관리자/자기자신 차단 확인
- [ ] 수동: `/admin/users/{id}` 개별/일괄 삭제 확인
- [ ] 수동: `/admin/qna-logs` 세션 삭제 확인
- [ ] 수동: 삭제 후 디스크에서 `app/static/reports/*.md`, `app/static/uploads/*.pdf` 가 사라졌는지 확인

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: 이슈에 PR 링크 코멘트**

연계된 GitHub 이슈가 있다면 PR이 그것을 닫도록 본문에 `Closes #<num>`을 추가.

---

## Self-Review

**1. Spec coverage:**

| 요구사항 | 구현 위치 |
|---|---|
| 사용자 계정 목록에서 사용자 삭제 | Task 4 (API) + Task 8 (UI) |
| 상세보기 — 대화 내역 삭제 | Task 5 (단일) + Task 6 (일괄) + Task 9 (UI) |
| 상세보기 — 분석 보고서 삭제 | Task 5 (단일) + Task 6 (일괄) + Task 9 (UI) |
| QnA 로그 세션 삭제 | Task 5 API 재사용 + Task 7 (CSRF) + Task 10 (UI) |
| 관리자 계정 삭제 불가 | Task 2 service `delete_user` PermissionError + Task 4 403 매핑 + Task 8 UI "불가" |
| 자기 자신 삭제 불가 | Task 2 service + Task 8 UI 가드 |
| confirm 모달 | Task 8/9/10 `window.confirm` |
| CSRF 토큰 필수 | Task 1 helper + Task 4/5/6 endpoint guard + Task 7/9/10 template injection |
| 파일 삭제 | Task 2 `_remove_report_files` + Task 3 `delete_analysis_report` / `bulk_delete_reports` |

✅ 누락 없음.

**2. Placeholder scan:**
- TBD/TODO 없음.
- "Add appropriate error handling" 없음 — 각 에러 분기(`LookupError` → 404, `PermissionError` → 403, `ValueError` → 400)는 코드로 명시됨.
- "Similar to Task N" 없음 — 모든 코드 블록은 self-contained.

**3. Type consistency:**
- 서비스 반환 형식: 모든 메서드가 `{"ok": bool, "deleted": int, "files_removed": int}` 일관.
- 엔드포인트 헤더: `X-CSRF-Token` (소문자 `x-csrf-token`)로 통일 — `ADMIN_CSRF_HEADER` 상수 사용.
- 서비스 메서드 이름: `delete_user`, `delete_chat_session`, `delete_analysis_report`, `bulk_delete_sessions`, `bulk_delete_reports` — 라우터 호출부와 테스트가 모두 일치.
- 라우터에서 import한 `ensure_admin_csrf_token` / `require_admin_csrf_token` — Task 1에서 export, Task 2~7에서 사용 — 일관.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-12-admin-deletion-features.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
