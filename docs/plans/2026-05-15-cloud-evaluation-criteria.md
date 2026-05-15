# Cloud-Sourced Evaluation Criteria Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use agent-team-driven-development to execute this plan.

**Goal:** Move evaluation criteria (`criteria`) to a cloud-as-source-of-truth model so changing the Gemini API key transparently swaps the local criteria set without losing the `title` / `display_alias` of items the new key already owns.

**Architecture:** Add a sidecar manifest stored in a dedicated Gemini File Search store (`rubric-metadata-store`). On startup, compare a stored sha256 hash of the API key with the current one; on mismatch, wipe the local `criteria` rows and the upload PDF cache, fetch the manifest, and rebuild. CRUD operations publish the manifest after every DB mutation. A new `app_state` key-value table holds the hash, last-synced-at, and `sync_state` (`ok` | `needs_resync` | `error`). A FastAPI dependency gates mutation routes; QnA degrades gracefully by skipping criteria citation when not `ok`.

**Tech Stack:** Python 3.x, FastAPI, SQLAlchemy async, Pydantic v2, Gemini File Search (`google-genai`), Jinja2 + Tailwind admin templates, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-15-cloud-evaluation-criteria-design.md`

---

## Wave Analysis

### Specialists

| Role | Expertise | Tasks |
|------|-----------|-------|
| backend-engineer | Python, FastAPI, SQLAlchemy async, Pydantic, Gemini File Search, pytest-asyncio | Tasks 1, 2, 3, 4, 5, 6, 7, 9 |
| frontend-engineer | Jinja2 templates, Tailwind, vanilla JS, FastAPI HTMX-style fetch patterns | Task 8 |

### Waves

**Wave 1: Foundation** — schema and value-object scaffolding that everything else imports
- Task 1 (backend-engineer) — `app_state` table + ORM model + migration helper + AppStateRepository + register migration in startup
- Task 2 (backend-engineer) — Manifest Pydantic schemas (`Manifest`, `ManifestEntry`)

  *Parallel-safe because:* Task 1 touches `app/models/app_state.py`, `app/repositories/app_state_repository.py`, `app/migrations/criteria_schema.py`, and adds one migration call line in `app/main.py`'s startup. Task 2 touches only `app/schemas/criteria_manifest.py`. Zero file overlap and no import relationship between the two.

**Wave 2: Services** — needs Wave 1 (uses AppStateRepository and the Manifest schemas)
- Task 3 (backend-engineer) — `CriteriaManifestService` (build/fetch/publish)
- Task 4 (backend-engineer) — `require_criteria_sync_ready` FastAPI dependency

  *Parallel-safe because:* Task 3 creates `app/services/criteria_manifest_service.py`; Task 4 adds a function to `app/dependencies.py`. Different files. Neither imports the other.
  *Depends on Wave 1:* Task 3 imports `Manifest` from `app/schemas/criteria_manifest.py` (Task 2). Task 4 imports `AppStateRepository` from `app/repositories/app_state_repository.py` (Task 1).

**Wave 3: Orchestrator** — needs Wave 2 (composes manifest service + state repo)
- Task 5 (backend-engineer) — `CriteriaReconciliationService` with lock, key-change detection, wipe + rebuild

  *Single-task wave:* no parallel work. Task 5 imports `AppStateRepository`, `CriteriaManifestService`, `CriteriaRepository`, and `CriteriaVectorService` to do the actual reconcile.
  *Depends on Wave 2:* `CriteriaManifestService` (Task 3) and `AppStateRepository` (Task 1).

**Wave 4: Integration** — needs Wave 3 (calls reconcile + uses dependency)
- Task 6 (backend-engineer) — Criteria admin router: attach `require_criteria_sync_ready` to mutations, call `publish_from_db()` after each CRUD, add `POST /api/admin/criteria/reconcile`, include sync metadata in `GET /api/admin/criteria` response
- Task 7 (backend-engineer) — Startup hook in `app/main.py` to schedule `reconcile()` as a non-blocking background task + feature flag `CRITERIA_CLOUD_RECONCILE_ENABLED` + env `FS_RUBRIC_METADATA_STORE_NAME` in `app/config.py`

  *Parallel-safe because:* Task 6 touches `app/routers/admin/criteria.py`; Task 7 touches `app/main.py` and `app/config.py`. No file overlap. Task 7 adds a different startup line than Task 1's migration call (both can append to `startup_event()` without conflict because each task creates exactly one new line and Wave 1 will have already committed Task 1's change before Wave 4 starts).
  *Depends on Wave 3:* Both call `CriteriaReconciliationService.reconcile()` (Task 5). Task 6 also depends on Task 3 (publish) and Task 4 (dependency function).

**Wave 5: User-facing** — needs Wave 4 (consumes sync metadata + reconcile endpoint)
- Task 8 (frontend-engineer) — Admin UI sync badge, "재동기화" button, mutation-disabled state in `app/templates/admin/criteria_list.html` + companion JS
- Task 9 (backend-engineer) — QnA citation guard: skip criteria citation and append a notice when `sync_state != ok`

  *Parallel-safe because:* Task 8 modifies Jinja template + static JS; Task 9 modifies `app/services/criteria_context_service.py` (and possibly the QnA orchestrator that calls it). Different files.
  *Depends on Wave 4:* Task 8 reads sync metadata from `GET /api/admin/criteria` (Task 6) and calls `POST /api/admin/criteria/reconcile` (Task 6). Task 9 reads `criteria_sync_state` via `AppStateRepository` (Task 1).

### Dependency Graph

```
Task 1 ─┬─→ Task 4 ─┐
        │           ├─→ Task 6 ─┐
Task 2 ──→ Task 3 ─┬┘            ├─→ Task 8
                   │             │
                   └─→ Task 5 ──┬→ Task 7
                                │
                                └→ Task 9 (via Task 1)
```

---

## Tasks

### Task 1: AppState Foundation

**Specialist:** backend-engineer
**Depends on:** None
**Produces:** `app.models.app_state.AppState` ORM model, `app.repositories.app_state_repository.AppStateRepository`, `ensure_app_state_table()` migration helper, registered in `app/main.py` `startup_event()`. Constants/keys: `KEY_API_KEY_HASH = "criteria_api_key_hash"`, `KEY_LAST_SYNCED_AT = "criteria_last_synced_at"`, `KEY_SYNC_STATE = "criteria_sync_state"`, `KEY_SYNC_ERROR = "criteria_sync_error"`. Enum-like string values: `"ok"`, `"needs_resync"`, `"error"`.

**Files:**
- Create: `app/models/app_state.py`
- Create: `app/repositories/app_state_repository.py`
- Modify: `app/migrations/criteria_schema.py` (append `ensure_app_state_table()`)
- Modify: `app/main.py` (call new migration in `startup_event()`)
- Create: `tests/unit/test_app_state_repository.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_app_state_repository.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_API_KEY_HASH,
    KEY_SYNC_STATE,
)


@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def repo(mock_db):
    return AppStateRepository(db=mock_db)


@pytest.mark.asyncio
async def test_get_returns_none_when_key_missing(repo, mock_db):
    result = AsyncMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    assert await repo.get("nonexistent") is None


@pytest.mark.asyncio
async def test_set_inserts_or_updates(repo, mock_db):
    result = AsyncMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    await repo.set(KEY_SYNC_STATE, "ok")
    mock_db.add.assert_called_once()
    mock_db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_set_many_persists_all_keys(repo, mock_db):
    result = AsyncMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    await repo.set_many({KEY_API_KEY_HASH: "abc", KEY_SYNC_STATE: "ok"})
    assert mock_db.add.call_count == 2
```

**Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/unit/test_app_state_repository.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.repositories.app_state_repository'`.

**Step 3: Write minimal implementation**

```python
# app/models/app_state.py
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func

from app.db import Base


class AppState(Base):
    """애플리케이션 상태 key-value 저장소"""

    __tablename__ = "app_state"

    key = Column(String(64), primary_key=True, comment="상태 키")
    value = Column(Text, nullable=False, comment="상태 값")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="마지막 갱신 시각",
    )
```

```python
# app/repositories/app_state_repository.py
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_state import AppState

logger = logging.getLogger(__name__)

KEY_API_KEY_HASH = "criteria_api_key_hash"
KEY_LAST_SYNCED_AT = "criteria_last_synced_at"
KEY_SYNC_STATE = "criteria_sync_state"
KEY_SYNC_ERROR = "criteria_sync_error"

SYNC_STATE_OK = "ok"
SYNC_STATE_NEEDS_RESYNC = "needs_resync"
SYNC_STATE_ERROR = "error"


class AppStateRepository:
    """app_state 테이블 read/write."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, key: str) -> Optional[str]:
        stmt = select(AppState).where(AppState.key == key)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        return row.value if row else None

    async def set(self, key: str, value: Optional[str]) -> None:
        stmt = select(AppState).where(AppState.key == key)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            self.db.add(AppState(key=key, value=value or ""))
        else:
            row.value = value or ""
        await self.db.flush()

    async def set_many(self, items: dict[str, Optional[str]]) -> None:
        for k, v in items.items():
            await self.set(k, v)
```

```python
# Append to app/migrations/criteria_schema.py
async def ensure_app_state_table(engine: AsyncEngine) -> bool:
    """app_state 테이블이 없을 경우 생성.

    Returns True 테이블이 새로 생성됨, False 이미 존재.
    """
    async with engine.begin() as conn:

        def _has_table(sync_conn) -> bool:
            from sqlalchemy import inspect

            return inspect(sync_conn).has_table("app_state")

        if await conn.run_sync(_has_table):
            logger.debug("app_state 테이블이 이미 존재하여 생성을 건너뜀")
            return False

        await conn.execute(
            text(
                "CREATE TABLE app_state ("
                "key VARCHAR(64) PRIMARY KEY, "
                "value TEXT NOT NULL, "
                "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        logger.info("app_state 테이블 생성 완료")
        return True
```

```python
# In app/main.py inside startup_event(), AFTER existing criteria migrations,
# add the following call (one line + log):
created = await ensure_app_state_table(engine)
if created:
    logger.info("app_state 테이블이 자동 생성되었습니다.")
```

Also add `from app.migrations.criteria_schema import ensure_app_state_table` near the other migration imports.

**Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/unit/test_app_state_repository.py -q
```

Expected: PASS, 3 tests.

**Step 5: Commit**

```bash
git add app/models/app_state.py \
        app/repositories/app_state_repository.py \
        app/migrations/criteria_schema.py \
        app/main.py \
        tests/unit/test_app_state_repository.py
git commit -m "feat(criteria-cloud): add app_state table, ORM model, and repository (wave 1)"
```

---

### Task 2: Manifest Pydantic Schema

**Specialist:** backend-engineer
**Depends on:** None
**Produces:** `app.schemas.criteria_manifest.Manifest`, `ManifestEntry`. Constants: `MANIFEST_SCHEMA_VERSION = 1`, `MANIFEST_FILENAME = "rubric-manifest.json"`.

**Files:**
- Create: `app/schemas/criteria_manifest.py`
- Create: `tests/unit/test_criteria_manifest_schema.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_criteria_manifest_schema.py
import pytest
from pydantic import ValidationError

from app.schemas.criteria_manifest import (
    Manifest,
    ManifestEntry,
    MANIFEST_SCHEMA_VERSION,
)


def test_manifest_round_trips():
    raw = {
        "schema_version": 1,
        "generated_at": "2026-05-15T03:21:00Z",
        "criteria": [
            {
                "document_id": "files/abc",
                "title": "rubric.pdf",
                "display_alias": "1학기 평가기준",
                "status": "active",
                "created_at": "2026-05-12T08:15:00Z",
                "activated_at": "2026-05-12T08:20:00Z",
            }
        ],
    }
    m = Manifest.model_validate(raw)
    assert m.schema_version == MANIFEST_SCHEMA_VERSION
    assert len(m.criteria) == 1
    assert m.criteria[0].display_alias == "1학기 평가기준"


def test_manifest_rejects_invalid_status():
    raw = {
        "schema_version": 1,
        "generated_at": "2026-05-15T03:21:00Z",
        "criteria": [
            {
                "document_id": "files/abc",
                "title": "r.pdf",
                "status": "weird",
            }
        ],
    }
    with pytest.raises(ValidationError):
        Manifest.model_validate(raw)


def test_manifest_empty_list_allowed():
    m = Manifest.model_validate(
        {
            "schema_version": 1,
            "generated_at": "2026-05-15T03:21:00Z",
            "criteria": [],
        }
    )
    assert m.criteria == []


def test_manifest_unknown_schema_version_rejected():
    raw = {
        "schema_version": 999,
        "generated_at": "2026-05-15T03:21:00Z",
        "criteria": [],
    }
    with pytest.raises(ValidationError):
        Manifest.model_validate(raw)
```

**Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/unit/test_criteria_manifest_schema.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write minimal implementation**

```python
# app/schemas/criteria_manifest.py
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "rubric-manifest.json"

CriteriaStatus = Literal["uploaded", "active", "archived"]


class ManifestEntry(BaseModel):
    """매니페스트의 평가기준 한 항목."""

    document_id: str = Field(..., description="Gemini File Search 문서 ID")
    title: str = Field(..., description="원본 파일명/불변 명칭")
    display_alias: Optional[str] = Field(default=None, description="사용자 편집 이름")
    status: CriteriaStatus = Field(..., description="상태")
    created_at: Optional[datetime] = Field(default=None)
    activated_at: Optional[datetime] = Field(default=None)


class Manifest(BaseModel):
    """rubric-metadata-store 에 저장되는 단일 매니페스트 문서."""

    schema_version: int = Field(...)
    generated_at: datetime = Field(...)
    criteria: List[ManifestEntry] = Field(default_factory=list)

    @field_validator("schema_version")
    def _supported_version(cls, v: int) -> int:
        if v != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"manifest schema v{v} unsupported "
                f"(current={MANIFEST_SCHEMA_VERSION})"
            )
        return v
```

**Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/unit/test_criteria_manifest_schema.py -q
```

Expected: PASS, 4 tests.

**Step 5: Commit**

```bash
git add app/schemas/criteria_manifest.py tests/unit/test_criteria_manifest_schema.py
git commit -m "feat(criteria-cloud): add Manifest pydantic schema (wave 1)"
```

---

### Task 3: CriteriaManifestService

**Specialist:** backend-engineer
**Depends on:** Task 2 (`Manifest`, `ManifestEntry`, `MANIFEST_FILENAME`)
**Produces:** `app.services.criteria_manifest_service.CriteriaManifestService` with `fetch()`, `publish_from_db()`, `upload(manifest)`, and exception class `CloudUnavailable`. Reads `settings.FS_RUBRIC_METADATA_STORE_NAME` (added in Task 7).

**Files:**
- Create: `app/services/criteria_manifest_service.py`
- Create: `tests/services/test_criteria_manifest_service.py`

**Step 1: Write the failing test**

```python
# tests/services/test_criteria_manifest_service.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.criteria_manifest import Manifest, ManifestEntry
from app.services.criteria_manifest_service import (
    CloudUnavailable,
    CriteriaManifestService,
)


@pytest.mark.asyncio
async def test_fetch_returns_empty_manifest_when_store_missing():
    fake_fs = AsyncMock()
    fake_fs.get_or_create_store = AsyncMock(return_value=("store-id", True))
    fake_fs.list_documents = AsyncMock(return_value=[])
    svc = CriteriaManifestService(file_search_service=fake_fs)
    m = await svc.fetch()
    assert isinstance(m, Manifest)
    assert m.criteria == []


@pytest.mark.asyncio
async def test_publish_from_db_uploads_manifest():
    fake_fs = AsyncMock()
    fake_fs.get_or_create_store = AsyncMock(return_value=("store-id", False))
    fake_fs.replace_single_document = AsyncMock(return_value="doc-id")

    fake_repo = AsyncMock()
    fake_repo.get_all_criteria = AsyncMock(
        return_value=[
            MagicMock(
                document_id="files/x",
                title="r.pdf",
                display_alias=None,
                status="active",
                created_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
                activated_at=None,
            )
        ]
    )

    svc = CriteriaManifestService(file_search_service=fake_fs)
    await svc.publish_from_db(fake_repo)
    fake_fs.replace_single_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_raises_cloud_unavailable_on_client_error():
    fake_fs = AsyncMock()
    fake_fs.get_or_create_store = AsyncMock(
        side_effect=RuntimeError("network down")
    )
    svc = CriteriaManifestService(file_search_service=fake_fs)
    with pytest.raises(CloudUnavailable):
        await svc.fetch()
```

**Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/services/test_criteria_manifest_service.py -q
```

Expected: FAIL (module not found).

**Step 3: Write minimal implementation**

```python
# app/services/criteria_manifest_service.py
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.config import settings
from app.schemas.criteria_manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    Manifest,
    ManifestEntry,
)
from app.services.file_search_service import FileSearchService

if TYPE_CHECKING:
    from app.repositories.criteria_repository import CriteriaRepository

logger = logging.getLogger(__name__)


class CloudUnavailable(RuntimeError):
    """Gemini File Search 동작 불가(네트워크/권한/5xx)."""


class CriteriaManifestService:
    """rubric-metadata-store 의 매니페스트 build/fetch/publish."""

    def __init__(self, file_search_service: FileSearchService | None = None):
        self.file_search_service = file_search_service or FileSearchService()
        self.store_name = settings.FS_RUBRIC_METADATA_STORE_NAME

    async def fetch(self) -> Manifest:
        try:
            store_id, _ = await self.file_search_service.get_or_create_store(
                self.store_name
            )
            docs = await self.file_search_service.list_documents(store_id)
        except Exception as exc:
            logger.warning("manifest fetch failed: %s", exc)
            raise CloudUnavailable(str(exc)) from exc

        manifest_doc = next(
            (d for d in docs if getattr(d, "display_name", "") == MANIFEST_FILENAME),
            None,
        )
        if manifest_doc is None:
            logger.info("매니페스트 문서가 없어 빈 매니페스트 반환")
            return Manifest(
                schema_version=MANIFEST_SCHEMA_VERSION,
                generated_at=datetime.now(tz=timezone.utc),
                criteria=[],
            )

        raw_bytes = await self.file_search_service.download_document_bytes(
            store_id, manifest_doc.id
        )
        return Manifest.model_validate_json(raw_bytes)

    async def upload(self, manifest: Manifest) -> None:
        try:
            store_id, _ = await self.file_search_service.get_or_create_store(
                self.store_name
            )
            payload = manifest.model_dump_json(by_alias=True).encode("utf-8")
            await self.file_search_service.replace_single_document(
                store_id=store_id,
                display_name=MANIFEST_FILENAME,
                content=payload,
                mime_type="application/json",
            )
            logger.info(
                "매니페스트 업로드 완료 (criteria=%d)", len(manifest.criteria)
            )
        except Exception as exc:
            logger.error("manifest upload failed: %s", exc)
            raise CloudUnavailable(str(exc)) from exc

    async def publish_from_db(
        self, criteria_repo: "CriteriaRepository"
    ) -> Manifest:
        rows = await criteria_repo.get_all_criteria()
        manifest = Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            generated_at=datetime.now(tz=timezone.utc),
            criteria=[
                ManifestEntry(
                    document_id=r.document_id,
                    title=r.title,
                    display_alias=r.display_alias,
                    status=r.status,
                    created_at=r.created_at,
                    activated_at=r.activated_at,
                )
                for r in rows
                if r.document_id is not None
            ],
        )
        await self.upload(manifest)
        return manifest
```

> NOTE for implementer: `FileSearchService` may not yet expose `replace_single_document`, `list_documents`, `download_document_bytes`, or `get_or_create_store` with these exact signatures. If a helper is missing, add the thinnest wrapper (≤15 lines) that calls the underlying `google.genai` client, and reuse the existing patterns in `criteria_vector_service.py`. Do not add unrelated features.

**Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/services/test_criteria_manifest_service.py -q
```

Expected: PASS, 3 tests.

**Step 5: Commit**

```bash
git add app/services/criteria_manifest_service.py \
        tests/services/test_criteria_manifest_service.py \
        app/services/file_search_service.py  # if helpers added
git commit -m "feat(criteria-cloud): add CriteriaManifestService (wave 2)"
```

---

### Task 4: require_criteria_sync_ready Dependency

**Specialist:** backend-engineer
**Depends on:** Task 1 (`AppStateRepository`, `KEY_SYNC_STATE`, `SYNC_STATE_OK`)
**Produces:** `app.dependencies.require_criteria_sync_ready` returning 503 when `sync_state != ok`.

**Files:**
- Modify: `app/dependencies.py` (append a new dependency function)
- Create: `tests/unit/test_require_criteria_sync_ready.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_require_criteria_sync_ready.py
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.dependencies import require_criteria_sync_ready


@pytest.mark.asyncio
async def test_passes_when_state_is_ok():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value="ok")
    # Should not raise
    await require_criteria_sync_ready(app_state_repo=repo)


@pytest.mark.asyncio
async def test_blocks_when_state_is_error():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value="error")
    with pytest.raises(HTTPException) as exc_info:
        await require_criteria_sync_ready(app_state_repo=repo)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_blocks_when_state_is_needs_resync():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value="needs_resync")
    with pytest.raises(HTTPException) as exc_info:
        await require_criteria_sync_ready(app_state_repo=repo)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_blocks_when_state_is_missing():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc_info:
        await require_criteria_sync_ready(app_state_repo=repo)
    assert exc_info.value.status_code == 503
```

**Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/unit/test_require_criteria_sync_ready.py -q
```

Expected: FAIL (`ImportError: cannot import name 'require_criteria_sync_ready'`).

**Step 3: Write minimal implementation**

```python
# Append to app/dependencies.py
from fastapi import Depends, HTTPException

from app.db import get_db
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_SYNC_STATE,
    SYNC_STATE_OK,
)


async def get_app_state_repo(db=Depends(get_db)) -> AppStateRepository:
    return AppStateRepository(db=db)


async def require_criteria_sync_ready(
    app_state_repo: AppStateRepository = Depends(get_app_state_repo),
) -> None:
    """평가기준 동기화 상태가 ok가 아니면 503."""
    state = await app_state_repo.get(KEY_SYNC_STATE)
    if state != SYNC_STATE_OK:
        raise HTTPException(
            status_code=503,
            detail=(
                "평가기준이 동기화 중이거나 사용할 수 없습니다. "
                "관리자 페이지에서 동기화 상태를 확인하세요."
            ),
        )
```

**Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/unit/test_require_criteria_sync_ready.py -q
```

Expected: PASS, 4 tests.

**Step 5: Commit**

```bash
git add app/dependencies.py tests/unit/test_require_criteria_sync_ready.py
git commit -m "feat(criteria-cloud): add require_criteria_sync_ready dependency (wave 2)"
```

---

### Task 5: CriteriaReconciliationService

**Specialist:** backend-engineer
**Depends on:** Task 1 (AppStateRepository, keys, sync_state constants), Task 2 (Manifest schemas), Task 3 (CriteriaManifestService, CloudUnavailable)
**Produces:** `app.services.criteria_reconciliation_service.CriteriaReconciliationService` with `reconcile() -> ReconcileResult`. Provides a module-level `_reconcile_lock = asyncio.Lock()`. Helper `_wipe_upload_dir()` validates the path with `Path.resolve(strict=True)` against `settings.CRITERIA_UPLOAD_DIR`.

**Files:**
- Create: `app/services/criteria_reconciliation_service.py`
- Create: `tests/services/test_criteria_reconciliation_service.py`

**Step 1: Write the failing test**

```python
# tests/services/test_criteria_reconciliation_service.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.app_state_repository import (
    KEY_API_KEY_HASH,
    KEY_SYNC_STATE,
    SYNC_STATE_OK,
)
from app.services.criteria_manifest_service import CloudUnavailable
from app.services.criteria_reconciliation_service import (
    CriteriaReconciliationService,
    ReconcileResult,
)
from app.schemas.criteria_manifest import Manifest, MANIFEST_SCHEMA_VERSION


def _empty_manifest():
    from datetime import datetime, timezone

    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        generated_at=datetime.now(tz=timezone.utc),
        criteria=[],
    )


@pytest.mark.asyncio
async def test_skips_when_hash_unchanged_and_state_ok():
    app_state = AsyncMock()
    app_state.get = AsyncMock(
        side_effect=lambda k: {
            KEY_API_KEY_HASH: "samehash",
            KEY_SYNC_STATE: SYNC_STATE_OK,
        }[k]
    )
    manifest_svc = AsyncMock()
    criteria_repo = AsyncMock()
    vector_svc = AsyncMock()

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="key",
    )
    with patch.object(svc, "_hash_key", return_value="samehash"):
        result = await svc.reconcile()
    assert result.skipped is True


@pytest.mark.asyncio
async def test_wipes_and_repopulates_on_key_change():
    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value="oldhash")
    app_state.set_many = AsyncMock()

    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(return_value=_empty_manifest())
    manifest_svc.upload = AsyncMock()

    criteria_repo = AsyncMock()
    criteria_repo.truncate = AsyncMock()
    criteria_repo.bulk_insert = AsyncMock()

    vector_svc = AsyncMock()
    vector_svc.list_document_ids = AsyncMock(return_value=[])

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="newkey",
    )

    with patch.object(svc, "_wipe_upload_dir"):
        result = await svc.reconcile()

    assert result.ok is True
    criteria_repo.truncate.assert_awaited()
    app_state.set_many.assert_awaited()


@pytest.mark.asyncio
async def test_cloud_unavailable_with_key_change_wipes_and_sets_error():
    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value="oldhash")
    app_state.set_many = AsyncMock()

    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(side_effect=CloudUnavailable("net"))

    criteria_repo = AsyncMock()
    criteria_repo.truncate = AsyncMock()
    vector_svc = AsyncMock()

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="newkey",
    )

    with patch.object(svc, "_wipe_upload_dir"):
        result = await svc.reconcile()

    assert result.ok is False
    criteria_repo.truncate.assert_awaited()
    args, _ = app_state.set_many.call_args
    assert args[0][KEY_SYNC_STATE] == "error"


@pytest.mark.asyncio
async def test_cloud_unavailable_without_key_change_marks_needs_resync():
    app_state = AsyncMock()
    app_state.get = AsyncMock(
        side_effect=lambda k: {
            KEY_API_KEY_HASH: "samehash",
            KEY_SYNC_STATE: "needs_resync",
        }[k]
    )
    app_state.set = AsyncMock()
    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(side_effect=CloudUnavailable("net"))
    criteria_repo = AsyncMock()
    vector_svc = AsyncMock()

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="key",
    )
    with patch.object(svc, "_hash_key", return_value="samehash"):
        result = await svc.reconcile()
    assert result.ok is False
    criteria_repo.truncate.assert_not_awaited()


@pytest.mark.asyncio
async def test_lock_serializes_concurrent_calls():
    import asyncio

    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value=None)
    app_state.set_many = AsyncMock()

    manifest_svc = AsyncMock()
    manifest_svc.fetch = AsyncMock(return_value=_empty_manifest())
    criteria_repo = AsyncMock()
    criteria_repo.truncate = AsyncMock()
    criteria_repo.bulk_insert = AsyncMock()
    vector_svc = AsyncMock()
    vector_svc.list_document_ids = AsyncMock(return_value=[])

    svc = CriteriaReconciliationService(
        app_state_repo=app_state,
        manifest_service=manifest_svc,
        criteria_repo=criteria_repo,
        vector_service=vector_svc,
        current_api_key="k",
    )

    with patch.object(svc, "_wipe_upload_dir"):
        await asyncio.gather(svc.reconcile(), svc.reconcile())

    # truncate called exactly twice (each reconcile got the lock once)
    assert criteria_repo.truncate.await_count == 2
```

**Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/services/test_criteria_reconciliation_service.py -q
```

Expected: FAIL (module not found).

**Step 3: Write minimal implementation**

```python
# app/services/criteria_reconciliation_service.py
import asyncio
import hashlib
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_API_KEY_HASH,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    SYNC_STATE_ERROR,
    SYNC_STATE_NEEDS_RESYNC,
    SYNC_STATE_OK,
)
from app.repositories.criteria_repository import CriteriaRepository
from app.schemas.criteria_manifest import (
    MANIFEST_SCHEMA_VERSION,
    Manifest,
    ManifestEntry,
)
from app.services.criteria_manifest_service import (
    CloudUnavailable,
    CriteriaManifestService,
)
from app.services.criteria_vector_service import CriteriaVectorService

logger = logging.getLogger(__name__)

_reconcile_lock = asyncio.Lock()


@dataclass
class ReconcileResult:
    ok: bool = False
    skipped: bool = False
    count: int = 0
    error: Optional[str] = None


class CriteriaReconciliationService:
    def __init__(
        self,
        app_state_repo: AppStateRepository,
        manifest_service: CriteriaManifestService,
        criteria_repo: CriteriaRepository,
        vector_service: CriteriaVectorService,
        current_api_key: Optional[str] = None,
    ):
        self.app_state = app_state_repo
        self.manifest_svc = manifest_service
        self.criteria_repo = criteria_repo
        self.vector_svc = vector_service
        self._api_key = current_api_key or settings.GOOGLE_API_KEY

    @staticmethod
    def _hash_key(api_key: Optional[str]) -> Optional[str]:
        if not api_key:
            return None
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def _wipe_upload_dir(self) -> None:
        target = Path(settings.CRITERIA_UPLOAD_DIR)
        resolved = target.resolve(strict=False)
        configured = Path(settings.CRITERIA_UPLOAD_DIR).resolve(strict=False)
        if resolved != configured:
            raise RuntimeError(
                f"refusing to wipe non-canonical upload dir: {resolved}"
            )
        if resolved.exists():
            shutil.rmtree(resolved)
        resolved.mkdir(parents=True, exist_ok=True)

    async def reconcile(self) -> ReconcileResult:
        async with _reconcile_lock:
            current_hash = self._hash_key(self._api_key)
            stored_hash = await self.app_state.get(KEY_API_KEY_HASH)
            stored_state = await self.app_state.get(KEY_SYNC_STATE)
            key_changed = stored_hash != current_hash

            if not key_changed and stored_state == SYNC_STATE_OK:
                return ReconcileResult(skipped=True)

            try:
                manifest = await self.manifest_svc.fetch()
                cloud_doc_ids = await self.vector_svc.list_document_ids()
            except CloudUnavailable as e:
                if key_changed:
                    try:
                        self._wipe_upload_dir()
                    except Exception as wipe_err:
                        logger.error("wipe failed: %s", wipe_err)
                    await self.criteria_repo.truncate()
                    await self.app_state.set_many(
                        {
                            KEY_API_KEY_HASH: current_hash,
                            KEY_SYNC_STATE: SYNC_STATE_ERROR,
                            KEY_SYNC_ERROR: str(e),
                        }
                    )
                else:
                    await self.app_state.set(KEY_SYNC_STATE, SYNC_STATE_NEEDS_RESYNC)
                    await self.app_state.set(KEY_SYNC_ERROR, str(e))
                return ReconcileResult(ok=False, error=str(e))

            manifest_ids = {e.document_id for e in manifest.criteria}
            cloud_ids = set(cloud_doc_ids)
            orphans_in_manifest = manifest_ids - cloud_ids
            orphans_in_cloud = cloud_ids - manifest_ids

            entries: list[ManifestEntry] = [
                e for e in manifest.criteria if e.document_id not in orphans_in_manifest
            ]
            for orphan_id in orphans_in_cloud:
                entries.append(
                    ManifestEntry(
                        document_id=orphan_id,
                        title=orphan_id,  # implementer: fetch display_name from cloud
                        display_alias=None,
                        status="uploaded",
                    )
                )

            await self.criteria_repo.truncate()
            await self.criteria_repo.bulk_insert(
                [
                    {
                        "title": e.title,
                        "document_id": e.document_id,
                        "display_alias": e.display_alias,
                        "status": e.status,
                        "created_at": e.created_at,
                        "activated_at": e.activated_at,
                    }
                    for e in entries
                ]
            )
            try:
                self._wipe_upload_dir()
            except Exception as e:
                logger.error("upload dir wipe failed: %s", e)

            if orphans_in_cloud:
                repaired = Manifest(
                    schema_version=MANIFEST_SCHEMA_VERSION,
                    generated_at=datetime.now(tz=timezone.utc),
                    criteria=entries,
                )
                try:
                    await self.manifest_svc.upload(repaired)
                except CloudUnavailable as e:
                    logger.warning("self-heal manifest upload failed: %s", e)

            await self.app_state.set_many(
                {
                    KEY_API_KEY_HASH: current_hash,
                    KEY_LAST_SYNCED_AT: datetime.now(tz=timezone.utc).isoformat(),
                    KEY_SYNC_STATE: SYNC_STATE_OK,
                    KEY_SYNC_ERROR: None,
                }
            )
            return ReconcileResult(ok=True, count=len(entries))
```

> NOTE for implementer: `CriteriaRepository.truncate()` and `bulk_insert()` are referenced but may not exist. Add them as thin async methods in `app/repositories/criteria_repository.py` (DELETE without WHERE + bulk `INSERT VALUES`), and commit them as part of this task. Re-use the existing repository's `db: AsyncSession` constructor.

**Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/services/test_criteria_reconciliation_service.py -q
```

Expected: PASS, 5 tests.

**Step 5: Commit**

```bash
git add app/services/criteria_reconciliation_service.py \
        app/repositories/criteria_repository.py \
        tests/services/test_criteria_reconciliation_service.py
git commit -m "feat(criteria-cloud): add CriteriaReconciliationService with lock (wave 3)"
```

---

### Task 6: Criteria Admin Router Wiring

**Specialist:** backend-engineer
**Depends on:** Task 3 (`CriteriaManifestService.publish_from_db`), Task 4 (`require_criteria_sync_ready`), Task 5 (`CriteriaReconciliationService.reconcile`)
**Produces:** Updated `app/routers/admin/criteria.py` with mutation routes calling `publish_from_db()` and gated by `require_criteria_sync_ready`, plus `POST /api/admin/criteria/reconcile` and `sync` metadata in `GET /api/admin/criteria`.

**Files:**
- Modify: `app/routers/admin/criteria.py`
- Create: `tests/routers/test_criteria_router_sync.py`

**Step 1: Write the failing test**

```python
# tests/routers/test_criteria_router_sync.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def admin_client(monkeypatch):
    # Stub auth dependency to admin user
    from app.dependencies import get_current_admin
    app.dependency_overrides[get_current_admin] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_reconcile_endpoint_returns_state(admin_client):
    fake_result = AsyncMock()
    with patch(
        "app.routers.admin.criteria.CriteriaReconciliationService"
    ) as svc_cls:
        instance = svc_cls.return_value
        instance.reconcile = AsyncMock(return_value=type("R", (), {
            "ok": True, "skipped": False, "count": 2, "error": None
        })())
        resp = admin_client.post("/api/admin/criteria/reconcile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["count"] == 2


def test_list_endpoint_includes_sync_metadata(admin_client):
    # Implementer: mock get_all_criteria and AppStateRepository.get
    pass  # leave skeleton; implementer fills with project's existing list-route test pattern


def test_mutation_blocked_when_sync_state_not_ok(admin_client):
    from app.dependencies import require_criteria_sync_ready
    from fastapi import HTTPException

    async def blocked():
        raise HTTPException(503, "blocked")

    app.dependency_overrides[require_criteria_sync_ready] = blocked
    resp = admin_client.post("/api/admin/criteria/upload", files={
        "file": ("r.pdf", b"data", "application/pdf")
    })
    assert resp.status_code == 503
```

**Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/routers/test_criteria_router_sync.py -q
```

Expected: FAIL (route or constructs missing).

**Step 3: Write minimal implementation**

In `app/routers/admin/criteria.py`:

1. Add imports:
   ```python
   from app.dependencies import require_criteria_sync_ready, get_app_state_repo
   from app.repositories.app_state_repository import (
       AppStateRepository,
       KEY_LAST_SYNCED_AT,
       KEY_SYNC_ERROR,
       KEY_SYNC_STATE,
   )
   from app.services.criteria_manifest_service import (
       CloudUnavailable,
       CriteriaManifestService,
   )
   from app.services.criteria_reconciliation_service import (
       CriteriaReconciliationService,
   )
   from app.services.criteria_vector_service import CriteriaVectorService
   ```

2. Attach `Depends(require_criteria_sync_ready)` to **every mutation route**: `upload`, `activate`, `display-alias PATCH`, `delete`. Read routes (`GET /api/admin/criteria`) MUST NOT have this dependency.

3. After each mutation completes its existing DB work, add:
   ```python
   manifest_svc = CriteriaManifestService()
   try:
       await manifest_svc.publish_from_db(criteria_repo)
   except CloudUnavailable as e:
       state_repo = AppStateRepository(db=db)
       await state_repo.set(KEY_SYNC_STATE, "needs_resync")
       await state_repo.set(KEY_SYNC_ERROR, str(e))
       raise HTTPException(
           status_code=502,
           detail=(
               "변경은 저장되었으나 클라우드 동기화에 실패했습니다. "
               "관리자 페이지에서 재동기화하세요."
           ),
       )
   ```

4. Modify the existing `GET /api/admin/criteria` response to include:
   ```python
   sync = {
       "state": await state_repo.get(KEY_SYNC_STATE),
       "last_synced_at": await state_repo.get(KEY_LAST_SYNCED_AT),
       "error": await state_repo.get(KEY_SYNC_ERROR),
   }
   ```
   Add it under a `"sync"` key in the response dict (or as a sibling field in the response model).

5. Add the new endpoint:
   ```python
   @router.post(
       "/reconcile",
       summary="평가기준 클라우드 재동기화",
       description="API key 변경/오류 후 클라우드에서 평가기준을 다시 가져옵니다.",
   )
   async def reconcile_criteria(
       db: AsyncSession = Depends(get_db),
       _admin=Depends(get_current_admin),
   ):
       state_repo = AppStateRepository(db=db)
       criteria_repo = CriteriaRepository(db=db)
       manifest_svc = CriteriaManifestService()
       vector_svc = CriteriaVectorService()
       svc = CriteriaReconciliationService(
           app_state_repo=state_repo,
           manifest_service=manifest_svc,
           criteria_repo=criteria_repo,
           vector_service=vector_svc,
       )
       result = await svc.reconcile()
       return {
           "ok": result.ok,
           "skipped": result.skipped,
           "count": result.count,
           "error": result.error,
           "sync_state": await state_repo.get(KEY_SYNC_STATE),
           "last_synced_at": await state_repo.get(KEY_LAST_SYNCED_AT),
       }
   ```

**Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/routers/test_criteria_router_sync.py -q
```

Expected: PASS, 3 tests.

**Step 5: Commit**

```bash
git add app/routers/admin/criteria.py tests/routers/test_criteria_router_sync.py
git commit -m "feat(criteria-cloud): wire publish_from_db + sync gate + reconcile endpoint (wave 4)"
```

---

### Task 7: Startup Hook & Config

**Specialist:** backend-engineer
**Depends on:** Task 5 (`CriteriaReconciliationService`)
**Produces:** New settings `FS_RUBRIC_METADATA_STORE_NAME` and `CRITERIA_CLOUD_RECONCILE_ENABLED`. Non-blocking reconcile scheduled in `startup_event()`.

**Files:**
- Modify: `app/config.py`
- Modify: `app/main.py`
- Create: `tests/test_startup_reconcile.py`

**Step 1: Write the failing test**

```python
# tests/test_startup_reconcile.py
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_startup_schedules_reconcile_when_enabled(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(
        main_module.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", True
    )
    with patch(
        "app.main._run_criteria_reconcile_in_background"
    ) as run:
        await main_module.startup_event()
    run.assert_called_once()


@pytest.mark.asyncio
async def test_startup_skips_reconcile_when_disabled(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(
        main_module.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", False
    )
    with patch(
        "app.main._run_criteria_reconcile_in_background"
    ) as run:
        await main_module.startup_event()
    run.assert_not_called()
```

**Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_startup_reconcile.py -q
```

Expected: FAIL (`AttributeError` on `_run_criteria_reconcile_in_background`).

**Step 3: Write minimal implementation**

```python
# app/config.py - add two fields inside Settings:
FS_RUBRIC_METADATA_STORE_NAME: str = Field(
    default="rubric-metadata-store",
    description="평가기준 매니페스트 저장용 File Search 스토어 이름",
)
CRITERIA_CLOUD_RECONCILE_ENABLED: bool = Field(
    default=True,
    description="평가기준 클라우드 reconcile 활성화 (긴급 차단 시 False)",
)
```

```python
# app/main.py - add near top:
import asyncio


async def _run_criteria_reconcile_in_background():
    """Schedule reconcile as a non-blocking task."""
    from app.db import AsyncSessionLocal
    from app.repositories.app_state_repository import AppStateRepository
    from app.repositories.criteria_repository import CriteriaRepository
    from app.services.criteria_manifest_service import CriteriaManifestService
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )
    from app.services.criteria_vector_service import CriteriaVectorService

    async def _task():
        try:
            async with AsyncSessionLocal() as db:
                svc = CriteriaReconciliationService(
                    app_state_repo=AppStateRepository(db=db),
                    manifest_service=CriteriaManifestService(),
                    criteria_repo=CriteriaRepository(db=db),
                    vector_service=CriteriaVectorService(),
                )
                result = await svc.reconcile()
                await db.commit()
                logger.info(
                    "startup reconcile result: ok=%s skipped=%s count=%d err=%s",
                    result.ok, result.skipped, result.count, result.error,
                )
        except Exception:
            logger.exception("startup reconcile crashed")

    asyncio.create_task(_task())


# Inside existing startup_event(), AFTER existing migrations:
if settings.CRITERIA_CLOUD_RECONCILE_ENABLED:
    await _run_criteria_reconcile_in_background()
```

**Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_startup_reconcile.py -q
```

Expected: PASS, 2 tests.

**Step 5: Commit**

```bash
git add app/config.py app/main.py tests/test_startup_reconcile.py
git commit -m "feat(criteria-cloud): startup reconcile hook + config flags (wave 4)"
```

---

### Task 8: Admin UI Sync Badge

**Specialist:** frontend-engineer
**Depends on:** Task 6 (sync metadata in `GET /api/admin/criteria` + `POST /reconcile` endpoint)
**Produces:** Updated `app/templates/admin/criteria_list.html` and any related JS file showing the badge, disabling mutation buttons when `sync_state != ok`, and surfacing a "재동기화" button that POSTs to `/api/admin/criteria/reconcile`.

**Files:**
- Modify: `app/templates/admin/criteria_list.html`
- Modify: `app/static/js/admin_criteria.js` (or whichever file currently drives this page — implementer to locate; if no JS file, add inline `<script>` block)
- Create: `tests/e2e/test_admin_criteria_sync_badge_smoke.py` (skip if e2e infra missing — fall back to a template render snapshot)

**Step 1: Write the failing test**

If the project has a template-render test pattern, use it. Otherwise, write a minimal smoke test that does an HTTP GET on the admin page with a mocked sync state and asserts the badge text appears:

```python
# tests/e2e/test_admin_criteria_sync_badge_smoke.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_badge_renders_ok():
    with patch(
        "app.routers.admin.criteria._fetch_sync_metadata",
        new_callable=AsyncMock,
        return_value={"state": "ok", "last_synced_at": "2026-05-15T00:00Z", "error": None},
    ):
        client = TestClient(app)
        # implementer: stub admin auth via dependency_overrides
        resp = client.get("/admin/criteria")
    assert "동기화 완료" in resp.text


def test_badge_renders_error_with_disabled_buttons():
    with patch(
        "app.routers.admin.criteria._fetch_sync_metadata",
        new_callable=AsyncMock,
        return_value={"state": "error", "last_synced_at": None, "error": "network down"},
    ):
        client = TestClient(app)
        resp = client.get("/admin/criteria")
    assert "동기화 실패" in resp.text
    assert 'data-disabled-when="not-ok"' in resp.text
```

> If `_fetch_sync_metadata` helper does not exist, the implementer creates it as a thin wrapper inside the router to make this testable (≤8 lines).

**Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/e2e/test_admin_criteria_sync_badge_smoke.py -q
```

Expected: FAIL.

**Step 3: Write minimal implementation**

In `criteria_list.html`, add at top of `{% block content %}`:

```html
{# Sync status badge — server-rendered #}
<div id="criteria-sync-status" class="mb-4 p-3 rounded border"
     data-state="{{ sync.state or 'unknown' }}">
  {% if sync.state == 'ok' %}
    <span class="text-green-700">● 동기화 완료</span>
    <span class="text-gray-500 text-sm ml-2">
      마지막 동기화 {{ sync.last_synced_at or '-' }}
    </span>
  {% elif sync.state == 'needs_resync' %}
    <span class="text-yellow-700">⚠ 동기화 필요</span>
    <button type="button"
            class="ml-3 px-2 py-1 text-sm bg-yellow-600 text-white rounded"
            data-action="reconcile">재동기화</button>
  {% else %}
    <span class="text-red-700">✗ 동기화 실패 — 평가기준 기능 비활성</span>
    {% if sync.error %}<div class="text-sm text-gray-600 mt-1">{{ sync.error }}</div>{% endif %}
    <button type="button"
            class="mt-2 px-2 py-1 text-sm bg-red-600 text-white rounded"
            data-action="reconcile">재동기화</button>
  {% endif %}
</div>
```

Add a `data-disabled-when="not-ok"` attribute to every mutation button (upload form submit, activate, alias edit save, delete). JS toggles `disabled` attribute when sync state is not `ok`.

In `admin_criteria.js` (or inline):

```javascript
document.addEventListener('DOMContentLoaded', () => {
  const status = document.getElementById('criteria-sync-status');
  if (!status) return;
  const state = status.dataset.state;
  if (state !== 'ok') {
    document.querySelectorAll('[data-disabled-when="not-ok"]')
      .forEach(el => { el.disabled = true; el.title = '동기화 필요'; });
  }
  document.querySelectorAll('[data-action="reconcile"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.textContent = '동기화 중...';
      try {
        const r = await fetch('/api/admin/criteria/reconcile', { method: 'POST' });
        const body = await r.json();
        alert(body.ok ? '동기화 완료' : `실패: ${body.error || ''}`);
        location.reload();
      } catch (e) {
        alert(`재동기화 호출 실패: ${e}`);
        btn.disabled = false;
        btn.textContent = '재동기화';
      }
    });
  });
});
```

Implementer also needs to plumb the `sync` dict into the existing `criteria_list.html` render call (the GET route in `app/routers/admin/criteria.py`).

**Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/e2e/test_admin_criteria_sync_badge_smoke.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/templates/admin/criteria_list.html \
        app/static/js/admin_criteria.js \
        tests/e2e/test_admin_criteria_sync_badge_smoke.py
git commit -m "feat(criteria-cloud): admin UI sync badge + reconcile button (wave 5)"
```

---

### Task 9: QnA Citation Guard

**Specialist:** backend-engineer
**Depends on:** Task 1 (`AppStateRepository.get(KEY_SYNC_STATE)`), Task 5 only conceptually (no code import)
**Produces:** Modified QnA criteria-citation path. When `sync_state != ok`, the QnA response skips criteria citation and appends a notice line "평가기준 동기화가 필요합니다."

**Files:**
- Modify: `app/services/criteria_context_service.py` (or the file the implementer finds owns criteria citation — confirm by grepping for `display_alias or title` per the explore report)
- Modify: caller in the QnA flow that builds the final response (likely under `app/routers/qna.py` or `app/services/qna_*`)
- Create: `tests/services/test_qna_criteria_citation_guard.py`

**Step 1: Write the failing test**

```python
# tests/services/test_qna_criteria_citation_guard.py
from unittest.mock import AsyncMock

import pytest

from app.repositories.app_state_repository import (
    KEY_SYNC_STATE,
    SYNC_STATE_OK,
)


@pytest.mark.asyncio
async def test_qna_skips_criteria_citation_when_sync_not_ok():
    from app.services.criteria_context_service import (
        build_criteria_context_or_notice,
    )

    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value="needs_resync")
    criteria_repo = AsyncMock()

    ctx, notice = await build_criteria_context_or_notice(
        app_state_repo=app_state,
        criteria_repo=criteria_repo,
    )
    assert ctx is None
    assert notice == "평가기준 동기화가 필요합니다."


@pytest.mark.asyncio
async def test_qna_builds_normal_context_when_sync_ok():
    from app.services.criteria_context_service import (
        build_criteria_context_or_notice,
    )

    app_state = AsyncMock()
    app_state.get = AsyncMock(return_value=SYNC_STATE_OK)
    criteria_repo = AsyncMock()
    criteria_repo.get_active_criteria = AsyncMock(return_value=[])

    ctx, notice = await build_criteria_context_or_notice(
        app_state_repo=app_state,
        criteria_repo=criteria_repo,
    )
    assert notice is None
    assert ctx is not None  # may be empty context object
```

**Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/services/test_qna_criteria_citation_guard.py -q
```

Expected: FAIL.

**Step 3: Write minimal implementation**

In `app/services/criteria_context_service.py`, add a wrapper:

```python
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_SYNC_STATE,
    SYNC_STATE_OK,
)


async def build_criteria_context_or_notice(
    app_state_repo: AppStateRepository,
    criteria_repo,
    # ... existing params used by the current build-context function ...
):
    state = await app_state_repo.get(KEY_SYNC_STATE)
    if state != SYNC_STATE_OK:
        return None, "평가기준 동기화가 필요합니다."
    # call the existing context-building function (rename/extract if needed)
    ctx = await _existing_build_criteria_context(criteria_repo)
    return ctx, None
```

In the QnA orchestrator that previously called the old criteria-context builder, replace that call with `build_criteria_context_or_notice(...)`. When `notice` is returned, append it to the assistant message body and skip criteria citation rendering.

**Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/services/test_qna_criteria_citation_guard.py -q
```

Expected: PASS, 2 tests.

**Step 5: Commit**

```bash
git add app/services/criteria_context_service.py \
        app/routers/qna.py \
        tests/services/test_qna_criteria_citation_guard.py
git commit -m "feat(criteria-cloud): QnA skips criteria citation when sync not ok (wave 5)"
```

---

## Execution

Plan complete and saved to `docs/plans/2026-05-15-cloud-evaluation-criteria.md`.

**Recommended: Agent Team-Driven** — Parallel specialist agents, wave-based execution, two-stage review after each task.

**Alternative: Subagent-Driven** — Serial execution, simpler orchestration, no team overhead. Better if <3 tasks or tasks are tightly coupled.

Which approach?
