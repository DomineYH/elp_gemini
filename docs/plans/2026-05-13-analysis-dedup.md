# Lesson Plan Analysis Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/api/lessonplan/analyze` reject re-analysis of an already-analyzed upload event with HTTP 409 + existing `report_id`, so the frontend can show "이미 분석된 문서입니다." and auto-open the existing report instead of re-calling Gemini.

**Architecture:** Define an upload **event** via a new `lessonplan_uploads` row created on every `/dashboard/upload` call. Bind each `analysis_reports` row to its source upload via a new `upload_id` FK with a UNIQUE index. The analyze service does a pre-flight check (latest upload already has a report? → 409) and catches the unique-index `IntegrityError` as a race-condition fallback. Existing 429 retry logic from PR #52 is left untouched.

**Tech Stack:** FastAPI · SQLAlchemy async · SQLite (UNIQUE INDEX in lieu of UNIQUE constraint) · pytest · pytest-asyncio · in-house `ensure_*(engine)` startup migration pattern (no Alembic).

---

## Spec Reference

See `docs/superpowers/specs/2026-05-13-analysis-dedup-design.md` for the full design. This plan implements that spec end-to-end.

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/models/lessonplan_uploads.py` | **Create** | `LessonPlanUpload` ORM model |
| `app/models/__init__.py` | **Modify** | Export `LessonPlanUpload` |
| `app/models/analysis_reports.py` | **Modify** | Add `upload_id` column + relationship |
| `app/migrations/lessonplan_uploads_table.py` | **Create** | `ensure_lessonplan_uploads_table(engine)` — idempotent CREATE TABLE + ALTER TABLE + CREATE UNIQUE INDEX |
| `app/migrations/__init__.py` | **Modify** | Export `ensure_lessonplan_uploads_table` |
| `app/main.py` | **Modify** | Call the new ensure_* function in `startup_event` |
| `app/services/lessonplan_storage_service.py` | **Modify** | `save_lessonplan` returns `file_hash` (SHA-256 of bytes) |
| `app/schemas/lessonplans.py` | **Modify** | `LessonPlanUploadResponse` includes `upload_id`, `file_hash` |
| `app/routers/lessonplans.py` | **Modify** | `upload_lessonplan` injects `db`, INSERTs `LessonPlanUpload`, returns `upload_id` |
| `app/services/lessonplan_analysis_service.py` | **Modify** | Pre-flight dedup check + race-condition `IntegrityError` fallback + set `upload_id` when saving report |
| `app/routers/lessonplan_analysis.py` | **Modify** | Add `ALREADY_ANALYZED` → HTTP 409 branch with `X-Report-Id` header |
| `app/templates/user/dashboard.html` | **Modify** | Branch on `response.status === 409` — toast + auto-open existing report |
| `tests/test_lessonplan_uploads_model.py` | **Create** | Model unit test |
| `tests/services/test_lessonplan_storage_service.py` | **Create** | Storage service hash test |
| `tests/services/test_lessonplan_analysis_service_dedup.py` | **Create** | Analyze service dedup tests (block / proceed / race fallback) |
| `tests/test_lessonplan_upload_router.py` | **Create** | Upload router returns `upload_id` |
| `tests/test_lessonplan_analysis_router_retry.py` | **Modify** | Add 409 case |
| `docs/plans/2026-05-13-fix-503-unavailable-retry.md` | **Delete** | Superseded — removed in Task 7 |

---

## Task 1: Data model + idempotent migration

**Files:**
- Create: `app/models/lessonplan_uploads.py`
- Modify: `app/models/__init__.py`
- Modify: `app/models/analysis_reports.py`
- Create: `app/migrations/lessonplan_uploads_table.py`
- Modify: `app/migrations/__init__.py`
- Modify: `app/main.py` (in `startup_event`)
- Test: `tests/test_lessonplan_uploads_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_lessonplan_uploads_model.py`:

```python
"""LessonPlanUpload 모델 및 마이그레이션 idempotency 테스트."""
import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db import Base
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from app.models.analysis_reports import AnalysisReport
from app.migrations.lessonplan_uploads_table import (
    ensure_lessonplan_uploads_table,
)


@pytest_asyncio.fixture
async def engine(tmp_path):
    db_path = tmp_path / "test.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_upload_row_can_be_inserted_and_linked_to_report(engine):
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as s:
        user = User(
            username="alice", nickname="alice",
            email="a@a.com", hashed_password="x",
        )
        s.add(user)
        await s.flush()

        up = LessonPlanUpload(
            user_id=user.id,
            filename="alice_plan.pdf",
            original_filename="plan.pdf",
            file_hash="a" * 64,
        )
        s.add(up)
        await s.flush()

        report = AnalysisReport(
            user_id=user.id,
            lessonplan_filename="alice_plan.pdf",
            lessonplan_original_name="plan.pdf",
            report_filename="r.md",
            report_path="/tmp/r.md",
            upload_id=up.id,
        )
        s.add(report)
        await s.commit()

        # Round-trip
        row = (
            await s.execute(
                select(AnalysisReport).where(
                    AnalysisReport.upload_id == up.id
                )
            )
        ).scalar_one()
        assert row.upload_id == up.id


@pytest.mark.asyncio
async def test_ensure_lessonplan_uploads_table_is_idempotent(tmp_path):
    """Migration should be safe to run twice and leave the schema valid."""
    db_path = tmp_path / "idempotent.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    # Build the rest of the schema first (users + analysis_reports baseline)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    added1 = await ensure_lessonplan_uploads_table(eng)
    added2 = await ensure_lessonplan_uploads_table(eng)

    # Either may report True the first time (depending on whether
    # Base.metadata.create_all already covered the new table), but
    # the second call must be a no-op (returns False).
    assert added2 is False

    def _columns(sync_conn):
        return {c["name"] for c in inspect(sync_conn).get_columns(
            "analysis_reports"
        )}

    async with eng.begin() as conn:
        cols = await conn.run_sync(_columns)
    assert "upload_id" in cols
    await eng.dispose()
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `uv run pytest tests/test_lessonplan_uploads_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.lessonplan_uploads'`.

- [ ] **Step 3: Create the `LessonPlanUpload` model**

Create `app/models/lessonplan_uploads.py`:

```python
"""
업로드 이벤트 모델
한 번의 업로드 액션 = 한 행. 분석 보고서와 1:1로 연결된다.
"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class LessonPlanUpload(Base):
    """수업 지도안 업로드 이벤트"""

    __tablename__ = "lessonplan_uploads"

    id = Column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    filename = Column(
        String(500),
        nullable=False,
        comment="서버 저장 파일명 ({username}_{original})",
    )
    original_filename = Column(
        String(500),
        nullable=True,
        comment="사용자 업로드 원본 파일명",
    )
    file_hash = Column(
        String(64),
        nullable=True,
        comment="SHA-256 of bytes — 향후 content-dedup 용",
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # 역방향 관계 (선택적)
    analysis_report = relationship(
        "AnalysisReport",
        back_populates="upload",
        uselist=False,
    )

    def __repr__(self):
        return (
            f"<LessonPlanUpload(id={self.id}, user_id={self.user_id}, "
            f"filename={self.filename})>"
        )
```

- [ ] **Step 4: Add `upload_id` to `AnalysisReport`**

Edit `app/models/analysis_reports.py`. After the `latency_ms` column (line 63) and before `created_at` (line 64), add:

```python
    upload_id = Column(
        Integer,
        ForeignKey("lessonplan_uploads.id"),
        nullable=True,
        comment="원본 업로드 이벤트 (1:1) — 중복 분석 방지 키",
    )
```

Then add the relationship at the end of the class, after the existing `user = relationship(...)` line:

```python
    upload = relationship(
        "LessonPlanUpload", back_populates="analysis_report"
    )
```

- [ ] **Step 5: Export the new model**

Edit `app/models/__init__.py` to import and export `LessonPlanUpload`. The exact diff depends on the file's current shape; the goal is `from app.models.lessonplan_uploads import LessonPlanUpload` is importable and listed in `__all__` if one exists. Add this import at the bottom of the existing imports:

```python
from app.models.lessonplan_uploads import LessonPlanUpload  # noqa: F401
```

(If `__all__` exists in the file, append `"LessonPlanUpload"` to it.)

- [ ] **Step 6: Create the idempotent migration**

Create `app/migrations/lessonplan_uploads_table.py`:

```python
"""
lessonplan_uploads 테이블 + analysis_reports.upload_id 컬럼 idempotent 적용.

SQLite은 ALTER TABLE ADD CONSTRAINT 를 지원하지 않으므로,
UNIQUE 제약 대신 UNIQUE INDEX 로 1:1 을 보장한다 (NULL 다중 허용은 동일).
"""
from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _collect_columns(sync_conn, table: str) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except NoSuchTableError:
        return None


def _collect_index_names(sync_conn, table: str) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except NoSuchTableError:
        return None


def _collect_table_names(sync_conn) -> Set[str]:
    return set(inspect(sync_conn).get_table_names())


async def ensure_lessonplan_uploads_table(engine: AsyncEngine) -> bool:
    """
    Idempotent 적용:
      1) lessonplan_uploads 테이블이 없으면 생성
      2) analysis_reports.upload_id 컬럼이 없으면 추가
      3) uq_analysis_reports_upload_id UNIQUE INDEX 가 없으면 생성

    Returns:
        하나라도 변경했으면 True, 모두 이미 있으면 False
    """
    async with engine.begin() as conn:
        tables = await conn.run_sync(_collect_table_names)
        changed = False

        if "lessonplan_uploads" not in tables:
            await conn.execute(text("""
                CREATE TABLE lessonplan_uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    filename VARCHAR(500) NOT NULL,
                    original_filename VARCHAR(500),
                    file_hash VARCHAR(64),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text(
                "CREATE INDEX ix_lessonplan_uploads_user_id "
                "ON lessonplan_uploads(user_id)"
            ))
            await conn.execute(text(
                "CREATE INDEX ix_lessonplan_uploads_created_at "
                "ON lessonplan_uploads(created_at)"
            ))
            logger.info("lessonplan_uploads 테이블 생성")
            changed = True

        ar_columns = await conn.run_sync(
            lambda c: _collect_columns(c, "analysis_reports")
        )
        if ar_columns is not None and "upload_id" not in ar_columns:
            await conn.execute(text(
                "ALTER TABLE analysis_reports "
                "ADD COLUMN upload_id INTEGER REFERENCES "
                "lessonplan_uploads(id)"
            ))
            logger.info("analysis_reports.upload_id 컬럼 추가")
            changed = True

        ar_indexes = await conn.run_sync(
            lambda c: _collect_index_names(c, "analysis_reports")
        )
        if (
            ar_indexes is not None
            and "uq_analysis_reports_upload_id" not in ar_indexes
        ):
            await conn.execute(text(
                "CREATE UNIQUE INDEX uq_analysis_reports_upload_id "
                "ON analysis_reports(upload_id) "
                "WHERE upload_id IS NOT NULL"
            ))
            logger.info(
                "analysis_reports.upload_id UNIQUE INDEX 생성"
            )
            changed = True

        return changed
```

- [ ] **Step 7: Register the migration in `app/migrations/__init__.py`**

Add an import and re-export. Open `app/migrations/__init__.py`, find the existing `from .users_lockout_columns import ensure_users_lockout_columns` line (around line 11), and add **below it**:

```python
from .lessonplan_uploads_table import ensure_lessonplan_uploads_table
```

Then add `"ensure_lessonplan_uploads_table"` to the `__all__` tuple (the file lists exports around line 21).

- [ ] **Step 8: Wire migration into startup**

Edit `app/main.py`. In the import block at line 23-28, add `ensure_lessonplan_uploads_table` to the import:

```python
from app.migrations import (
    ensure_criteria_file_path_column,
    ensure_criteria_display_alias_column,
    ensure_user_profiles_table,
    ensure_users_lockout_columns,
    ensure_lessonplan_uploads_table,
)
```

In `startup_event` (around line 209, immediately after the existing `profiles_patched = await ensure_user_profiles_table(engine)` block and **before** `renamed = await rename_chat_session_in_service_teacher_label(engine)` at line 215), add:

```python
    uploads_patched = await ensure_lessonplan_uploads_table(engine)
    if uploads_patched:
        logger.info(
            "lessonplan_uploads / analysis_reports.upload_id 자동 적용"
        )
```

- [ ] **Step 9: Run the tests to confirm they pass**

Run: `uv run pytest tests/test_lessonplan_uploads_model.py -v`
Expected: both tests PASS.

- [ ] **Step 10: Commit**

```bash
git add app/models/lessonplan_uploads.py app/models/__init__.py \
        app/models/analysis_reports.py \
        app/migrations/lessonplan_uploads_table.py \
        app/migrations/__init__.py app/main.py \
        tests/test_lessonplan_uploads_model.py
git commit -m "feat(db): add lessonplan_uploads table + analysis_reports.upload_id FK

New model with idempotent ensure_lessonplan_uploads_table migration:
creates the table, adds the upload_id column, and creates a partial
UNIQUE INDEX (SQLite-friendly alternative to ALTER ADD CONSTRAINT)
that allows multiple NULL upload_id rows but blocks duplicate non-NULL.

upload_id is nullable so legacy analysis_reports rows do not need
backfill."
```

---

## Task 2: Storage service returns `file_hash`

**Files:**
- Modify: `app/services/lessonplan_storage_service.py`
- Test: `tests/services/test_lessonplan_storage_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/services/__init__.py` (empty) if it does not exist:

```bash
mkdir -p tests/services
touch tests/services/__init__.py
```

Create `tests/services/test_lessonplan_storage_service.py`:

```python
"""LessonPlanStorageService 추가 동작 테스트."""
import hashlib

import pytest

from app.services.lessonplan_storage_service import (
    LessonPlanStorageService,
)


def test_save_lessonplan_returns_file_hash(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    content = b"hello world"
    result = svc.save_lessonplan(
        username="alice",
        original_filename="plan.pdf",
        file_content=content,
    )
    assert "file_hash" in result
    assert result["file_hash"] == hashlib.sha256(content).hexdigest()
    assert len(result["file_hash"]) == 64


def test_save_lessonplan_different_content_different_hash(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    r1 = svc.save_lessonplan(
        username="alice", original_filename="a.pdf",
        file_content=b"aaa",
    )
    r2 = svc.save_lessonplan(
        username="alice", original_filename="b.pdf",
        file_content=b"bbb",
    )
    assert r1["file_hash"] != r2["file_hash"]
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `uv run pytest tests/services/test_lessonplan_storage_service.py -v`
Expected: FAIL with `KeyError: 'file_hash'` or `assert 'file_hash' in result`.

- [ ] **Step 3: Add hash computation to `save_lessonplan`**

Edit `app/services/lessonplan_storage_service.py`. Add `import hashlib` at the top of the file (after the existing `import os` line).

In `save_lessonplan` (line 36-71), replace the body so the returned dict includes the SHA-256:

```python
    def save_lessonplan(
        self,
        username: str,
        original_filename: str,
        file_content: bytes,
    ) -> Dict[str, str]:
        """
        지도안 파일 저장

        Returns:
            {
              "file_path": str,
              "filename": str,
              "timestamp": str (ISO),
              "file_hash": str (SHA-256 hex, 64 chars),
            }
        """
        try:
            filename = f"{username}_{original_filename}"
            file_path = self.base_dir / filename

            with open(file_path, "wb") as f:
                f.write(file_content)

            file_hash = hashlib.sha256(file_content).hexdigest()

            logger.info(
                f"지도안 저장 완료: {filename} (hash={file_hash[:8]}…)"
            )

            return {
                "file_path": str(file_path),
                "filename": filename,
                "timestamp": datetime.now().isoformat(),
                "file_hash": file_hash,
            }
        except Exception as e:
            logger.error(f"지도안 저장 실패: {str(e)}")
            raise
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/services/test_lessonplan_storage_service.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/lessonplan_storage_service.py \
        tests/services/__init__.py \
        tests/services/test_lessonplan_storage_service.py
git commit -m "feat(storage): return file_hash (SHA-256) from save_lessonplan

Returned in the result dict so the upload router can persist it on
the lessonplan_uploads row for future content-dedup features."
```

---

## Task 3: Upload router persists `LessonPlanUpload` row

**Files:**
- Modify: `app/schemas/lessonplans.py`
- Modify: `app/routers/lessonplans.py`
- Test: `tests/test_lessonplan_upload_router.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_lessonplan_upload_router.py`:

```python
"""Upload 라우터가 lessonplan_uploads 행을 만들고 upload_id 를 반환하는지 검증."""
import pytest
import pytest_asyncio
from io import BytesIO
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import app
from app.dependencies import get_current_user, get_db
from app.db import Base
from app.models.users import User
from app.models.lessonplan_uploads import LessonPlanUpload


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "t.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    yield factory
    await eng.dispose()


@pytest_asyncio.fixture
async def client(session_factory, tmp_path, monkeypatch):
    # Storage writes to a tmp dir so the test doesn't pollute repo data/
    monkeypatch.setenv("PYTEST_TMP_LESSONPLAN_DIR", str(tmp_path / "lp"))

    # Stub LessonPlanStorageService to use tmp dir
    from app.services import lessonplan_storage_service as svc_mod
    original_init = svc_mod.LessonPlanStorageService.__init__

    def patched_init(self, base_dir=None):
        original_init(self, base_dir=str(tmp_path / "lp"))

    monkeypatch.setattr(
        svc_mod.LessonPlanStorageService,
        "__init__",
        patched_init,
    )

    # Seed a user
    async with session_factory() as s:
        u = User(
            username="alice", nickname="alice",
            email="a@a.com", hashed_password="x",
        )
        s.add(u)
        await s.commit()
        user_id = u.id

    async def override_get_user():
        async with session_factory() as s:
            return (
                await s.execute(
                    select(User).where(User.id == user_id)
                )
            ).scalar_one()

    async def override_get_db():
        async with session_factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, session_factory

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_upload_creates_lessonplan_upload_row(client):
    c, session_factory = client
    pdf_bytes = (
        b"%PDF-1.4\n%fake pdf for test\n"
        b"1 0 obj\n<<>>\nendobj\n%%EOF\n"
    )
    files = {"file": ("plan.pdf", BytesIO(pdf_bytes), "application/pdf")}

    res = await c.post("/dashboard/upload", files=files)

    assert res.status_code == 201
    body = res.json()
    assert "upload_id" in body
    assert isinstance(body["upload_id"], int)
    assert body["upload_id"] > 0

    async with session_factory() as s:
        rows = (
            await s.execute(select(LessonPlanUpload))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == body["upload_id"]
        assert rows[0].original_filename == "plan.pdf"
        assert rows[0].file_hash is not None
        assert len(rows[0].file_hash) == 64


@pytest.mark.asyncio
async def test_two_uploads_same_filename_produce_two_rows(client):
    c, session_factory = client
    pdf_bytes = b"%PDF-1.4\nfake\n%%EOF\n"
    files1 = {"file": ("plan.pdf", BytesIO(pdf_bytes), "application/pdf")}
    files2 = {"file": ("plan.pdf", BytesIO(pdf_bytes), "application/pdf")}

    r1 = await c.post("/dashboard/upload", files=files1)
    r2 = await c.post("/dashboard/upload", files=files2)

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["upload_id"] != r2.json()["upload_id"]

    async with session_factory() as s:
        rows = (
            await s.execute(select(LessonPlanUpload))
        ).scalars().all()
        assert len(rows) == 2
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `uv run pytest tests/test_lessonplan_upload_router.py -v`
Expected: FAIL — response body has no `upload_id` field; no rows inserted.

- [ ] **Step 3: Add `upload_id` + `file_hash` to the upload response schema**

Edit `app/schemas/lessonplans.py`. Replace `LessonPlanUploadResponse` (lines 10-24) with:

```python
class LessonPlanUploadResponse(BaseModel):
    """지도안 업로드 응답"""

    filename: str = Field(..., description="저장된 파일명")
    original_filename: str = Field(..., description="원본 파일명")
    file_size: int = Field(..., description="파일 크기 (bytes)")
    saved_path: str = Field(..., description="저장 경로")
    upload_id: int = Field(..., description="업로드 이벤트 ID")
    file_hash: str = Field(
        ..., description="파일 SHA-256 (64자 hex)"
    )
```

- [ ] **Step 4: Make the upload route insert the row**

Edit `app/routers/lessonplans.py`. Add these imports near the top with the others:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.lessonplan_uploads import LessonPlanUpload
```

Replace the `upload_lessonplan` handler (lines 39-96) with:

```python
@router.post(
    "/upload",
    response_model=LessonPlanUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="지도안 업로드",
    description="사용자의 지도안 파일을 업로드합니다.",
)
async def upload_lessonplan(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    지도안 파일 업로드 + lessonplan_uploads 행 생성
    """
    try:
        validator = FileValidator()
        validation_result = await validator.validate_file(file)
        if not validation_result["valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=validation_result["error"],
            )

        file_content = await file.read()

        storage_service = LessonPlanStorageService()
        saved = storage_service.save_lessonplan(
            username=current_user.username,
            original_filename=file.filename,
            file_content=file_content,
        )

        upload = LessonPlanUpload(
            user_id=current_user.id,
            filename=saved["filename"],
            original_filename=file.filename,
            file_hash=saved["file_hash"],
        )
        db.add(upload)
        await db.flush()

        logger.info(
            f"지도안 업로드 성공: user={current_user.username}, "
            f"file={saved['filename']}, upload_id={upload.id}"
        )

        return LessonPlanUploadResponse(
            filename=saved["filename"],
            original_filename=file.filename,
            file_size=len(file_content),
            saved_path=saved["file_path"],
            upload_id=upload.id,
            file_hash=saved["file_hash"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"지도안 업로드 실패: {str(e)}", exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="파일 업로드 중 오류가 발생했습니다.",
        )
```

- [ ] **Step 5: Run the test to confirm it passes**

Run: `uv run pytest tests/test_lessonplan_upload_router.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Run the broader test surface to confirm no regression**

Run: `uv run pytest tests/ -x -k "lessonplan or upload"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/schemas/lessonplans.py app/routers/lessonplans.py \
        tests/test_lessonplan_upload_router.py
git commit -m "feat(upload): persist lessonplan_uploads row on every upload

Each /dashboard/upload now creates a new lessonplan_uploads
row (even for same filename overwrites) and returns upload_id +
file_hash in the response. This is the anchor the analyze service
uses to detect duplicate analysis."
```

---

## Task 4: Analyze service — dedup pre-flight + race-condition fallback

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py`
- Test: `tests/services/test_lessonplan_analysis_service_dedup.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/services/test_lessonplan_analysis_service_dedup.py`:

```python
"""LessonPlanAnalysisService 중복 분석 차단 동작 테스트."""
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.exc import IntegrityError

from app.db import Base
from app.models.users import User
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.analysis_reports import AnalysisReport
from app.services.lessonplan_analysis_service import (
    LessonPlanAnalysisService,
)


@pytest_asyncio.fixture
async def session(tmp_path):
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/t.db"
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Create the partial unique index that production migration adds
        from sqlalchemy import text
        await conn.execute(text(
            "CREATE UNIQUE INDEX uq_analysis_reports_upload_id "
            "ON analysis_reports(upload_id) "
            "WHERE upload_id IS NOT NULL"
        ))
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        yield s
    await eng.dispose()


async def _seed_user_and_upload(s):
    u = User(
        username="alice", nickname="alice",
        email="a@a.com", hashed_password="x",
    )
    s.add(u)
    await s.flush()
    up = LessonPlanUpload(
        user_id=u.id,
        filename="alice_plan.pdf",
        original_filename="plan.pdf",
        file_hash="a" * 64,
    )
    s.add(up)
    await s.flush()
    await s.commit()
    return u, up


@pytest.mark.asyncio
async def test_analyze_blocks_when_upload_already_analyzed(session):
    u, up = await _seed_user_and_upload(session)
    existing = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=up.filename,
        lessonplan_original_name=up.original_filename,
        report_filename="r.md",
        report_path="/tmp/r.md",
        upload_id=up.id,
    )
    session.add(existing)
    await session.commit()

    svc = LessonPlanAnalysisService(db=session)

    # Gemini client must NOT be called
    with patch.object(
        svc, "_get_store_ids"
    ) as mock_stores, patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search"
    ) as mock_gemini:
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id, username=u.username,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == existing.id
    assert mock_stores.call_count == 0
    assert mock_gemini.call_count == 0


@pytest.mark.asyncio
async def test_analyze_proceeds_when_no_existing_report(session):
    u, up = await _seed_user_and_upload(session)
    svc = LessonPlanAnalysisService(db=session)

    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    with patch.object(
        svc, "_get_store_ids", return_value=["user-store", "rubric-store"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.lessonplan_storage, "list_lessonplans",
        return_value=[{
            "filename": up.filename,
            "original_filename": up.original_filename,
            "created_at": "2026-05-13T00:00:00",
        }],
    ), patch.object(
        svc.report_storage, "save_report",
        return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id, username=u.username,
        )

    assert result["success"] is True

    saved = (
        await session.execute(
            select(AnalysisReport).where(AnalysisReport.upload_id == up.id)
        )
    ).scalar_one()
    assert saved.upload_id == up.id


@pytest.mark.asyncio
async def test_analyze_race_fallback_on_integrity_error(session):
    u, up = await _seed_user_and_upload(session)

    # Pre-existing report — simulates "other request finished first"
    winner = AnalysisReport(
        user_id=u.id,
        lessonplan_filename=up.filename,
        lessonplan_original_name=up.original_filename,
        report_filename="r.md",
        report_path="/tmp/r.md",
        upload_id=up.id,
    )
    session.add(winner)
    await session.commit()

    svc = LessonPlanAnalysisService(db=session)

    # Force the dedup pre-check to MISS (simulate a TOCTOU race) by
    # patching the inner query to return None just for this call.
    # Then the INSERT below will hit IntegrityError, which should
    # be caught and converted to ALREADY_ANALYZED.
    fake_response = MagicMock()
    fake_response.text = "# Report\n\nbody"
    fake_response.candidates = []

    real_find = svc._find_existing_report_for_latest_upload

    call_count = {"n": 0}

    async def racing_find(username):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call (pre-flight) — pretend nothing is there yet
            return (up, None)
        # Second call (after IntegrityError) — real lookup finds winner
        return await real_find(username)

    with patch.object(
        svc, "_find_existing_report_for_latest_upload",
        side_effect=racing_find,
    ), patch.object(
        svc, "_get_store_ids", return_value=["u", "r"]
    ), patch.object(
        svc.prompt_loader, "get_prompt", return_value="SYS"
    ), patch(
        "app.services.lessonplan_analysis_service."
        "_call_gemini_with_file_search",
        return_value=fake_response,
    ), patch.object(
        svc.lessonplan_storage, "list_lessonplans",
        return_value=[{
            "filename": up.filename,
            "original_filename": up.original_filename,
            "created_at": "2026-05-13T00:00:00",
        }],
    ), patch.object(
        svc.report_storage, "save_report",
        return_value={"filename": "r.md", "file_path": "/tmp/r.md"},
    ):
        result = await svc.analyze_lesson_plan(
            session_id=1, user_id=u.id, username=u.username,
        )

    assert result["success"] is False
    assert result["error_code"] == "ALREADY_ANALYZED"
    assert result["report_id"] == winner.id
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/services/test_lessonplan_analysis_service_dedup.py -v`
Expected: FAIL — `_find_existing_report_for_latest_upload` does not exist; analyze does not return `ALREADY_ANALYZED`.

- [ ] **Step 3: Add the dedup helper + integrate into `analyze_lesson_plan`**

Edit `app/services/lessonplan_analysis_service.py`.

Add this import near the top with the other imports:

```python
from sqlalchemy.exc import IntegrityError
from app.models.lessonplan_uploads import LessonPlanUpload
```

Add the helper method to the `LessonPlanAnalysisService` class. Place it **after** `_get_store_ids` (which ends around line 243) and **before** `_build_analysis_prompt`:

```python
    async def _find_existing_report_for_latest_upload(
        self, username: str
    ):
        """
        사용자의 최신 업로드 이벤트와 그에 연결된 기존 보고서를 함께 조회.

        Returns:
            (LessonPlanUpload | None, AnalysisReport | None)
            - (None, None): 업로드 이력 자체가 없는 사용자
            - (upload, None): 최신 업로드는 있으나 분석 보고서는 아직 없음
            - (upload, report): 이미 분석 완료 → 차단해야 함
        """
        from sqlalchemy.orm import joinedload

        result = await self.db.execute(
            select(User)
            .where(User.username == username)
            .limit(1)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return (None, None)

        upload_result = await self.db.execute(
            select(LessonPlanUpload)
            .where(LessonPlanUpload.user_id == user.id)
            .order_by(LessonPlanUpload.created_at.desc())
            .limit(1)
        )
        latest_upload = upload_result.scalar_one_or_none()
        if latest_upload is None:
            return (None, None)

        report_result = await self.db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.upload_id == latest_upload.id)
            .limit(1)
        )
        existing_report = report_result.scalar_one_or_none()
        return (latest_upload, existing_report)
```

This helper needs `select` and `User`. Add to the imports at the top of the file:

```python
from sqlalchemy import select
from app.models.users import User
```

Now modify `analyze_lesson_plan`. Inside the existing `async with asyncio.timeout(180):` block (after line 94), **before** the existing `# 1. File Search Store ID 조회` block at line 95, insert the pre-flight check:

```python
                # 0. 중복 분석 차단 — 최신 업로드에 이미 보고서가 있으면
                # 즉시 ALREADY_ANALYZED 반환 (Gemini 호출 안 함)
                latest_upload, existing_report = (
                    await self._find_existing_report_for_latest_upload(
                        username
                    )
                )
                if existing_report is not None:
                    logger.info(
                        f"중복 분석 차단: upload_id={latest_upload.id}, "
                        f"existing report_id={existing_report.id}"
                    )
                    return {
                        "success": False,
                        "error_code": "ALREADY_ANALYZED",
                        "error": "이미 분석된 문서입니다.",
                        "report_id": existing_report.id,
                    }
```

Then in the existing report-save block, find the existing `analysis_record = AnalysisReport(...)` construction (lines 172-179) and **set `upload_id`** on it. Replace those lines with:

```python
                        analysis_record = AnalysisReport(
                            user_id=user_id,
                            lessonplan_filename=lessonplan_filename,
                            lessonplan_original_name=original_filename,
                            report_filename=saved_report["filename"],
                            report_path=saved_report["file_path"],
                            latency_ms=latency_ms,
                            upload_id=(
                                latest_upload.id
                                if latest_upload is not None
                                else None
                            ),
                        )
                        self.db.add(analysis_record)
                        try:
                            await self.db.flush()
                        except IntegrityError:
                            # Race: another request inserted a report for
                            # this upload_id between our pre-flight check
                            # and this INSERT. Roll back and return
                            # ALREADY_ANALYZED with the winning row's id.
                            await self.db.rollback()
                            _, winner = (
                                await self._find_existing_report_for_latest_upload(
                                    username
                                )
                            )
                            if winner is not None:
                                logger.warning(
                                    f"분석 결과 race 감지 → ALREADY_ANALYZED "
                                    f"폴백 (winner report_id={winner.id})"
                                )
                                return {
                                    "success": False,
                                    "error_code": "ALREADY_ANALYZED",
                                    "error": "이미 분석된 문서입니다.",
                                    "report_id": winner.id,
                                }
                            raise
                        logger.info(
                            f"분석 기록 DB 저장 완료: "
                            f"id={analysis_record.id}, "
                            f"upload_id={analysis_record.upload_id}"
                        )
```

(Remove the original `await self.db.flush()` + `logger.info(f"분석 기록 DB 저장 완료...")` two lines — they are replaced by the block above.)

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `uv run pytest tests/services/test_lessonplan_analysis_service_dedup.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Run regression on existing analyze tests**

Run: `uv run pytest tests/ -x -k "analysis or lessonplan"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/lessonplan_analysis_service.py \
        tests/services/test_lessonplan_analysis_service_dedup.py
git commit -m "fix(analysis): block duplicate analysis at the service layer

Adds a pre-flight check: if the user's latest lessonplan_uploads row
already has an AnalysisReport, return error_code=ALREADY_ANALYZED
with the existing report_id and DO NOT call Gemini.

On the INSERT of a fresh report, catch the unique-index IntegrityError
that fires when two concurrent analyses race for the same upload_id,
re-fetch the winning row, and return ALREADY_ANALYZED — so the loser
never surfaces a 500."
```

---

## Task 5: Analyze router — `ALREADY_ANALYZED` → HTTP 409

**Files:**
- Modify: `app/routers/lessonplan_analysis.py`
- Modify: `tests/test_lessonplan_analysis_router_retry.py`

- [ ] **Step 1: Write the failing test (append to existing router test file)**

Add this test to `tests/test_lessonplan_analysis_router_retry.py` after the existing `test_analyze_returns_429_on_resource_exhausted`:

```python
@pytest.mark.asyncio
async def test_analyze_returns_409_on_already_analyzed(client):
    """ALREADY_ANALYZED 에러 코드 시 HTTP 409 + report_id 반환"""
    mock_result = {
        "success": False,
        "error": "이미 분석된 문서입니다.",
        "error_code": "ALREADY_ANALYZED",
        "report_id": 17,
    }

    with patch(
        "app.routers.lessonplan_analysis.LessonPlanAnalysisService"
    ) as MockService:
        instance = MockService.return_value
        instance.analyze_lesson_plan = AsyncMock(return_value=mock_result)

        res = await client.post(
            "/api/lessonplan/analyze",
            json={"session_id": 1},
        )

    assert res.status_code == 409
    body = res.json()
    assert body["detail"] == "이미 분석된 문서입니다."
    assert body["report_id"] == 17
    assert res.headers.get("x-report-id") == "17"
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `uv run pytest tests/test_lessonplan_analysis_router_retry.py::test_analyze_returns_409_on_already_analyzed -v`
Expected: FAIL — status is 500, not 409.

- [ ] **Step 3: Add the 409 branch to the router**

Edit `app/routers/lessonplan_analysis.py`. Find the existing `if not result.get("success"):` block (around lines 55-65) and **insert a new branch before the existing `RESOURCE_EXHAUSTED` branch**. The full replacement for that `if not result.get("success"):` block is:

```python
        if not result.get("success"):
            if result.get("error_code") == "ALREADY_ANALYZED":
                report_id = result.get("report_id")
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={
                        "detail": result.get(
                            "error", "이미 분석된 문서입니다."
                        ),
                        "report_id": report_id,
                    },
                    headers={"X-Report-Id": str(report_id)},
                )
            if result.get("error_code") == "RESOURCE_EXHAUSTED":
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=result.get("error", "잠시 후 다시 시도해주세요."),
                    headers={"Retry-After": "30"},
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "분석 중 오류 발생"),
            )
```

The reason for `JSONResponse` (not `HTTPException`) on the 409 path: we want the JSON body to contain both `detail` and `report_id` as siblings — `HTTPException`'s `detail` is the entire body. `JSONResponse` lets us shape the body precisely.

Add the import at the top of the file (after the existing `from fastapi.responses import FileResponse`):

```python
from fastapi.responses import FileResponse, JSONResponse
```

(Combine the two `from fastapi.responses import ...` lines into one if the file already has the FileResponse import — keep it on a single line.)

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_lessonplan_analysis_router_retry.py -v`
Expected: all 4 tests PASS (existing 429 + 500 + new 409 + any others).

- [ ] **Step 5: Commit**

```bash
git add app/routers/lessonplan_analysis.py \
        tests/test_lessonplan_analysis_router_retry.py
git commit -m "fix(router): return HTTP 409 + report_id when upload already analyzed

Maps the new ALREADY_ANALYZED service result to a 409 Conflict with
both a JSON body ({detail, report_id}) and an X-Report-Id header,
so the frontend can show 'already analyzed' and auto-open the
existing report viewer."
```

---

## Task 6: Frontend dashboard — 409 handler

**Files:**
- Modify: `app/templates/user/dashboard.html` — `startAnalysis()` function, lines 1129-1167

The existing function (verified against the current file):

```javascript
    async function startAnalysis() {
        const loadingOverlay = document.getElementById('loadingOverlay');
        const loadingText = loadingOverlay.querySelector('h3');
        const loadingDesc = loadingOverlay.querySelector('p');

        loadingText.textContent = '수업 지도안 분석 중...';
        loadingDesc.textContent = 'AI가 수업 지도안을 체계적으로 분석하고 있습니다. 약 1-3분 정도 소요됩니다.';
        loadingOverlay.classList.remove('hidden');

        try {
            const response = await fetch('/api/lessonplan/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: 1 })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '분석 요청 실패');
            }

            const data = await response.json();

            if (data.success) {
                showAnalysisResult(data.report);
            } else {
                throw new Error(data.error || '분석 실패');
            }

        } catch (error) {
            alert('오류가 발생했습니다: ' + error.message);
        } finally {
            loadingOverlay.classList.add('hidden');
            loadingText.textContent = '문서 처리 중...';
            loadingDesc.textContent = 'AI가 문서를 분석하고 있습니다. 잠시만 기다려주세요.';
        }
    }
```

Helpers we will reuse (already in the file): `showAnalysisResult(markdownReport)` (line 1169) renders Markdown into the `analysisModal`; `alert()` is the file's existing message-display convention; `loadingOverlay.classList.add('hidden')` hides loading. The reports API (`GET /api/lessonplan/reports/{id}`) returns `{id, content, ...}` per `app/routers/lessonplan_analysis.py:113-158` — pass `.content` into `showAnalysisResult`.

- [ ] **Step 1: Insert the 409 branch before the existing `if (!response.ok)` check**

Edit `app/templates/user/dashboard.html`. Find the lines:

```javascript
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '분석 요청 실패');
            }
```

(starting at line 1146). Replace those 4 lines with:

```javascript
            if (response.status === 409) {
                const data = await response.json();
                const reportId = data.report_id
                    ?? response.headers.get('X-Report-Id');
                alert(data.detail || '이미 분석된 문서입니다.');
                if (reportId) {
                    const r = await fetch(
                        `/api/lessonplan/reports/${reportId}`,
                        { credentials: 'same-origin' }
                    );
                    if (r.ok) {
                        const report = await r.json();
                        showAnalysisResult(report.content);
                    }
                }
                return;
            }

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '분석 요청 실패');
            }
```

Do **not** touch the `try`/`catch`/`finally` envelope. The `finally` block already hides the loading overlay, so the 409 `return` falls through to it correctly.

- [ ] **Step 2: Manual smoke test**

```bash
uv run uvicorn app.main:app --reload
```

In a browser:
1. Log in as a normal user.
2. Upload a PDF. Click [분석하기]. Wait for analysis to complete — report renders.
3. Click [분석하기] **again** (do not re-upload). Expected: toast "이미 분석된 문서입니다." + the existing report appears in the viewer. Server log shows `중복 분석 차단: upload_id=…, existing report_id=…` and **zero** new Gemini calls.
4. Upload again (same file or different file). Click [분석하기]. Expected: a new analysis runs successfully (a second report appears in the dashboard's "내 분석 보고서" list).

- [ ] **Step 3: Commit**

```bash
git add app/templates/user/dashboard.html
git commit -m "feat(dashboard): handle 409 from analyze — alert and open existing report

On HTTP 409 from /api/lessonplan/analyze the handler reads report_id
from the body (or X-Report-Id header), shows an alert, fetches the
existing report from /api/lessonplan/reports/{id}, and passes its
content to showAnalysisResult — reusing the same renderer the
success path uses."
```

---

## Task 7: Cleanup — close issue #53

**Files:**
- GitHub: close issue [#53](https://github.com/DomineYH/elp_gemini/issues/53)

The superseded 503 retry plan file was never committed to the branch (it was a mid-session artifact removed before implementation began), so no file deletion is needed.

- [ ] **Step 1: Close GitHub issue #53**

```bash
gh issue close 53 \
  --repo DomineYH/elp_gemini \
  --comment "Superseded by the analysis-dedup design (docs/superpowers/specs/2026-05-13-analysis-dedup-design.md) and its implementation plan (docs/plans/2026-05-13-analysis-dedup.md). Blocking duplicate analysis at the service layer addresses the root cause of repeated Gemini calls; the 503 retry treated a symptom. PR #52's 429 retry is preserved unchanged."
```

- [ ] **Step 2: (Optional) Open a tracking issue for the dedup work**

```bash
gh issue create \
  --repo DomineYH/elp_gemini \
  --title "feat: deduplicate lesson plan analysis by upload event" \
  --body "Implementation tracked in docs/plans/2026-05-13-analysis-dedup.md. Spec: docs/superpowers/specs/2026-05-13-analysis-dedup-design.md."
```

---

## Acceptance Criteria (mirror of spec)

- [ ] New upload + [분석하기] once → analysis succeeds and `analysis_reports.upload_id` is set on the new row.
- [ ] Re-click [분석하기] on the same upload → HTTP 409 + `X-Report-Id` header + JSON `report_id`; server log shows zero new Gemini calls.
- [ ] Frontend on 409 → toast "이미 분석된 문서입니다" + viewer auto-opens the report identified by `report_id`.
- [ ] After uploading any file again → [분석하기] runs normally.
- [ ] Two concurrent [분석하기] clicks on the same upload → both end as HTTP 409 (loser via `IntegrityError` race fallback, no uncaught 500).
- [ ] PR #52's 429 retry behavior preserved (existing regression test stays green).
- [ ] `uv run pytest tests/ -x` passes.

## Out of Scope

- Content-hash-based dedup across uploads (`file_hash` is stored, not branched on).
- Backfill of pre-existing `AnalysisReport` rows (they stay `upload_id IS NULL`).
- Gemini 503 retry — see deleted plan; superseded by dedup.

## Verification

```bash
# Full plan verification suite
uv run pytest tests/test_lessonplan_uploads_model.py \
              tests/services/test_lessonplan_storage_service.py \
              tests/test_lessonplan_upload_router.py \
              tests/services/test_lessonplan_analysis_service_dedup.py \
              tests/test_lessonplan_analysis_router_retry.py \
              -v

# Full regression
uv run pytest tests/ -x

# Manual smoke
uv run uvicorn app.main:app --reload
# Then: upload → analyze → re-click analyze → upload again → analyze
```
