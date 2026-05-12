# Criteria Display Alias Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use agent-team-driven-development to execute this plan.

**Goal:** Introduce an editable `display_alias` column on `criteria` so every UI surface (admin list/detail, user dashboard, QnA citations, cloud-store table) shows the same human-readable name without modifying anything in the Gemini File Search cloud store.

**Architecture:** Add `display_alias VARCHAR(255) NULL` to the `criteria` table via a startup migration helper (matching existing `ensure_criteria_file_path_column` pattern). Repository, schema, and a single PATCH endpoint expose the new field. Five Jinja/JS surfaces consume `(display_alias or title)` through a fallback. No cloud-side re-upload — alias is DB-only.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic v1 validators, Jinja2 templates, vanilla JS, pytest.

**Reference design:** [docs/superpowers/specs/2026-05-12-criteria-display-alias-design.md](../superpowers/specs/2026-05-12-criteria-display-alias-design.md)

---

## Wave Analysis

### Specialists

| Role | Expertise | Tasks |
|------|-----------|-------|
| backend-engineer | Python, FastAPI, SQLAlchemy async, Pydantic, pytest, Alembic-style migrations | Tasks 1, 2, 3, 4, 5, 6, 7 |
| frontend-engineer | Jinja2, Tailwind, vanilla JS, fetch API, inline editing UX | Tasks 8, 9, 10, 11 |

### Waves

**Wave 1: Foundation** — schema + validators land first so every downstream layer can rely on the column and the request shape.
- Task 1 (backend-engineer) — Add `display_alias` column to `Criteria` model + startup migration helper.
- Task 2 (backend-engineer) — Add `UpdateDisplayAliasRequest` Pydantic schema with ASCII validation.

  *Parallel-safe because:* Task 1 touches `app/models/criteria.py`, `app/migrations/criteria_schema.py`, `app/migrations/__init__.py`, `app/main.py`. Task 2 touches only `app/schemas/criteria.py`. No import relationship in either direction (the schema does not import the model).

**Wave 2: Backend layer** — repository methods + service-side alias fallback. Both need the column from Wave 1.
- Task 3 (backend-engineer) — Add `update_display_alias` and `get_criteria_map_by_document_ids` to `CriteriaRepository`.
- Task 7 (backend-engineer) — Apply `(display_alias or title)` fallback in `CriteriaContextService.get_criteria_context()` and the citation builder.

  *Parallel-safe because:* Task 3 modifies only `app/repositories/criteria_repository.py`. Task 7 modifies only `app/services/criteria_context_service.py`. Task 7 reads `criteria.display_alias` via the ORM attribute added in Wave 1 (does not need new repository methods).
  *Depends on Wave 1:* `Criteria.display_alias` ORM attribute exists.

**Wave 3: Routers** — PATCH endpoint, admin view enrichment, user view data-source swap. All need Wave 2 outputs.
- Task 4 (backend-engineer) — Add `PATCH /api/admin/criteria/{id}/display-alias` endpoint.
- Task 5 (backend-engineer) — Enrich admin `criteria_list` view: zip cloud docs with DB criteria; expose `display_alias` on `criteria_items`.
- Task 6 (backend-engineer) — Switch `views.user_dashboard` and `views.upload_document` to DB-based criteria list with alias fallback.

  *Parallel-safe because:* Three different files — `app/routers/admin/criteria.py`, `app/routers/admin/criteria_views.py`, `app/routers/views.py`. No imports among them.
  *Depends on Wave 2:* Task 4 uses `update_display_alias` + `UpdateDisplayAliasRequest`. Task 5 uses `get_criteria_map_by_document_ids`. Task 6 uses `get_active_criteria` (existing) plus `display_alias` attribute.

**Wave 4: Templates + JS** — visual layer reads the data shapes produced in Wave 3.
- Task 8 (frontend-engineer) — Update `templates/admin/criteria_list.html` (top table alias sub-line + bottom cloud table columns).
- Task 9 (frontend-engineer) — Update `templates/admin/criteria_detail.html` (alias display + edit affordance).
- Task 10 (frontend-engineer) — Update `templates/user/dashboard.html` to render `criteria.name` (alias-or-title).

  *Parallel-safe because:* Three different template files, no cross-template includes for the affected blocks.
  *Depends on Wave 3:* Task 8 needs the enriched `cloud_documents` shape from Task 5 and `display_alias` on `criteria_items.documents`. Task 9 needs `criteria.display_alias` exposed by `criteria_detail` view (already passes the ORM object). Task 10 needs the `criteria_documents = [{name: ...}]` shape from Task 6.

**Wave 5: JS wiring** — inline edit needs both the PATCH endpoint (Wave 3) and the rendered alias cells (Wave 4).
- Task 11 (frontend-engineer) — Add inline alias edit JS in `app/static/js/criteria_list.js`.

  *Parallel-safe because:* Single task in wave.
  *Depends on Wave 3:* PATCH endpoint from Task 4. *Depends on Wave 4:* `.alias-cell` markup from Task 8.

### Dependency Graph

```
Task 1 ──┬─→ Task 3 ──┬─→ Task 4 ──┐
         │            │             │
         │            └─→ Task 5 ──┤
         │                          │
         ├─→ Task 6 ────────────────┤
         │                          │
         └─→ Task 7                 │
Task 2 ──────→ Task 4               │
                                    │
Task 4 ──→ Task 11                  │
Task 5 ──→ Task 8 ──→ Task 11       │
Task 5 ──→ Task 9 ──────────────────┘
Task 6 ──→ Task 10
```

---

## Tasks

### Task 1: Add `display_alias` column to Criteria model and startup migration

**Specialist:** backend-engineer
**Depends on:** None
**Produces:**
- New ORM attribute `Criteria.display_alias: Mapped[str | None]` available across the app.
- Startup-time migration that adds the column to existing SQLite/MySQL databases without manual intervention.

**Files:**
- Modify: `app/models/criteria.py`
- Modify: `app/migrations/criteria_schema.py`
- Modify: `app/migrations/__init__.py`
- Modify: `app/main.py`
- Create: `tests/test_criteria_display_alias_migration.py`

**Step 1: Write the failing test**

```python
# tests/test_criteria_display_alias_migration.py
"""display_alias 컬럼 마이그레이션 테스트"""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import ensure_criteria_display_alias_column


@pytest.mark.asyncio
async def test_adds_display_alias_when_missing(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    # 기존 스키마(컬럼 없음) 생성
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE criteria ("
                "id INTEGER PRIMARY KEY, "
                "title VARCHAR(255) NOT NULL, "
                "document_id VARCHAR(500), "
                "file_size BIGINT NOT NULL, "
                "file_path VARCHAR(500) NOT NULL, "
                "status VARCHAR(50) NOT NULL, "
                "uploaded_by VARCHAR(255) NOT NULL, "
                "activated_at DATETIME, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "synced_at DATETIME)"
            )
        )

    patched = await ensure_criteria_display_alias_column(engine)
    assert patched is True

    # 컬럼이 추가되었는지 확인
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("criteria")}
        )
    assert "display_alias" in cols

    # 두 번째 호출 시에는 no-op (False)
    patched_again = await ensure_criteria_display_alias_column(engine)
    assert patched_again is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_skips_when_table_missing(tmp_path):
    db_path = tmp_path / "empty.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    patched = await ensure_criteria_display_alias_column(engine)
    assert patched is False
    await engine.dispose()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_criteria_display_alias_migration.py -x`
Expected: FAIL — `ImportError: cannot import name 'ensure_criteria_display_alias_column'`

**Step 3: Write minimal implementation**

In `app/models/criteria.py`, add the column after `synced_at`:

```python
    display_alias = Column(
        String(255),
        nullable=True,
        comment="관리자 편집용 ASCII 표시명 (NULL이면 title을 fallback)"
    )
```

In `app/migrations/criteria_schema.py`, append a sibling helper modeled on `ensure_criteria_file_path_column`:

```python
async def ensure_criteria_display_alias_column(
    engine: AsyncEngine,
) -> bool:
    """
    criteria.display_alias 컬럼이 없을 경우 추가
    Returns True 컬럼이 새로 추가됨, False 이미 존재하거나 테이블 없음
    """
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_criteria_columns)
        if columns is None:
            logger.warning(
                "criteria 테이블이 없어 display_alias 패치를 건너뜀"
            )
            return False
        if "display_alias" in columns:
            logger.debug(
                "criteria.display_alias 컬럼이 이미 존재하여 패치를 건너뜀"
            )
            return False

        await conn.execute(
            text(
                "ALTER TABLE criteria "
                "ADD COLUMN display_alias VARCHAR(255) NULL"
            )
        )
        logger.info("criteria.display_alias 컬럼을 추가함")
        return True
```

In `app/migrations/__init__.py`, export the new helper:

```python
from .criteria_schema import (
    ensure_criteria_file_path_column,
    ensure_criteria_display_alias_column,
)

__all__ = [
    "ensure_criteria_file_path_column",
    "ensure_criteria_display_alias_column",
    # ...existing exports
]
```

In `app/main.py`, near the existing `ensure_criteria_file_path_column` invocation inside `startup_event`:

```python
    alias_patched = await ensure_criteria_display_alias_column(engine)
    if alias_patched:
        logger.info("criteria.display_alias 컬럼이 자동 추가되었습니다.")
```

And add `ensure_criteria_display_alias_column` to the imports at the top of `app/main.py`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_criteria_display_alias_migration.py -x`
Expected: PASS — both tests green.

**Step 5: Commit**

```bash
git add app/models/criteria.py app/migrations/criteria_schema.py app/migrations/__init__.py app/main.py tests/test_criteria_display_alias_migration.py
git commit -m "feat(criteria): add display_alias column with startup migration"
```

---

### Task 2: Add Pydantic schema for alias update

**Specialist:** backend-engineer
**Depends on:** None
**Produces:**
- `UpdateDisplayAliasRequest` schema available at `app.schemas.criteria` for Task 4.
- ASCII validation contract usable by both the router (server-side) and JS (mirrored client-side).

**Files:**
- Modify: `app/schemas/criteria.py`
- Create: `tests/test_criteria_display_alias_schema.py`

**Step 1: Write the failing test**

```python
# tests/test_criteria_display_alias_schema.py
"""display_alias 검증 스키마 테스트"""
import pytest
from pydantic import ValidationError

from app.schemas.criteria import UpdateDisplayAliasRequest


def test_accepts_ascii():
    req = UpdateDisplayAliasRequest(display_alias="elementary-6-math")
    assert req.display_alias == "elementary-6-math"


def test_strips_whitespace():
    req = UpdateDisplayAliasRequest(display_alias="  alias-1  ")
    assert req.display_alias == "alias-1"


def test_empty_string_becomes_none():
    req = UpdateDisplayAliasRequest(display_alias="")
    assert req.display_alias is None


def test_whitespace_only_becomes_none():
    req = UpdateDisplayAliasRequest(display_alias="   ")
    assert req.display_alias is None


def test_none_stays_none():
    req = UpdateDisplayAliasRequest(display_alias=None)
    assert req.display_alias is None


def test_rejects_korean():
    with pytest.raises(ValidationError) as exc_info:
        UpdateDisplayAliasRequest(display_alias="평가기준-1")
    assert "ASCII" in str(exc_info.value)


def test_rejects_emoji():
    with pytest.raises(ValidationError):
        UpdateDisplayAliasRequest(display_alias="alias-🎯")


def test_rejects_over_255_chars():
    with pytest.raises(ValidationError) as exc_info:
        UpdateDisplayAliasRequest(display_alias="a" * 256)
    assert "255" in str(exc_info.value)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_criteria_display_alias_schema.py -x`
Expected: FAIL — `ImportError: cannot import name 'UpdateDisplayAliasRequest'`

**Step 3: Write minimal implementation**

Append to `app/schemas/criteria.py`:

```python
from pydantic import BaseModel, validator
from typing import Optional


class UpdateDisplayAliasRequest(BaseModel):
    """평가기준 표시명(alias) 업데이트 요청"""

    display_alias: Optional[str] = None

    @validator("display_alias")
    def validate_alias(cls, v):
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if not v.isascii():
            raise ValueError("ASCII 문자만 허용됩니다.")
        if len(v) > 255:
            raise ValueError("표시명은 255자 이내로 입력하세요.")
        return v


class UpdateDisplayAliasResponse(BaseModel):
    """평가기준 표시명 업데이트 응답"""

    success: bool
    criteria_id: int
    display_alias: Optional[str]
```

If `BaseModel`/`validator` are already imported at the top of the file, do not re-import.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_criteria_display_alias_schema.py -x`
Expected: PASS — all 8 cases green.

**Step 5: Commit**

```bash
git add app/schemas/criteria.py tests/test_criteria_display_alias_schema.py
git commit -m "feat(criteria): add UpdateDisplayAliasRequest schema with ASCII validation"
```

---

### Task 3: Repository methods for alias update and document lookup

**Specialist:** backend-engineer
**Depends on:** Task 1 (Criteria.display_alias ORM attribute)
**Produces:**
- `CriteriaRepository.update_display_alias(criteria_id, alias) -> Criteria | None`
- `CriteriaRepository.get_criteria_map_by_document_ids(doc_ids) -> dict[str, Criteria]`

**Files:**
- Modify: `app/repositories/criteria_repository.py`
- Create: `tests/test_criteria_repository_alias.py`

**Step 1: Write the failing test**

```python
# tests/test_criteria_repository_alias.py
"""CriteriaRepository alias 관련 메서드 테스트"""
import pytest
from app.repositories.criteria_repository import CriteriaRepository


@pytest.mark.asyncio
async def test_update_display_alias_sets_value(async_session):
    repo = CriteriaRepository(async_session)
    created = await repo.save_criteria(
        title="orig.pdf",
        file_size=10,
        uploaded_by="admin",
        file_path="/tmp/orig.pdf",
        document_id=None,
        status="uploaded",
    )
    await async_session.commit()

    updated = await repo.update_display_alias(created.id, "alias-1")
    assert updated is not None
    assert updated.display_alias == "alias-1"


@pytest.mark.asyncio
async def test_update_display_alias_clears_with_none(async_session):
    repo = CriteriaRepository(async_session)
    created = await repo.save_criteria(
        title="orig.pdf",
        file_size=10,
        uploaded_by="admin",
        file_path="/tmp/orig.pdf",
        document_id=None,
        status="uploaded",
    )
    await async_session.commit()

    await repo.update_display_alias(created.id, "alias-2")
    cleared = await repo.update_display_alias(created.id, None)
    assert cleared.display_alias is None


@pytest.mark.asyncio
async def test_update_display_alias_missing_id_returns_none(async_session):
    repo = CriteriaRepository(async_session)
    result = await repo.update_display_alias(99999, "alias-x")
    assert result is None


@pytest.mark.asyncio
async def test_get_criteria_map_by_document_ids(async_session):
    repo = CriteriaRepository(async_session)
    c1 = await repo.save_criteria(
        title="a.pdf",
        file_size=1,
        uploaded_by="admin",
        file_path="/tmp/a.pdf",
        document_id="doc-aaa",
        status="active",
    )
    c2 = await repo.save_criteria(
        title="b.pdf",
        file_size=1,
        uploaded_by="admin",
        file_path="/tmp/b.pdf",
        document_id="doc-bbb",
        status="active",
    )
    await async_session.commit()

    mapping = await repo.get_criteria_map_by_document_ids(
        ["doc-aaa", "doc-bbb", "doc-missing"]
    )
    assert mapping["doc-aaa"].id == c1.id
    assert mapping["doc-bbb"].id == c2.id
    assert "doc-missing" not in mapping
```

If `async_session` fixture is not present in `tests/conftest.py`, follow whatever fixture pattern existing repository tests use (e.g., `tests/test_criteria_repository.py` — open it and reuse the same fixture name).

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_criteria_repository_alias.py -x`
Expected: FAIL — `AttributeError: 'CriteriaRepository' object has no attribute 'update_display_alias'`

**Step 3: Write minimal implementation**

Append to `app/repositories/criteria_repository.py`:

```python
    async def update_display_alias(
        self,
        criteria_id: int,
        alias: Optional[str],
    ) -> Optional[Criteria]:
        """
        criteria.display_alias 업데이트

        Args:
            criteria_id: 평가기준 ID
            alias: 새 alias (None이면 NULL로 설정)

        Returns:
            업데이트된 Criteria 또는 None (해당 ID 없음)
        """
        criteria = await self.get_criteria_by_id(criteria_id)
        if criteria is None:
            logger.warning(
                f"display_alias 업데이트 실패 (없음): id={criteria_id}"
            )
            return None
        criteria.display_alias = alias
        await self.db.flush()
        await self.db.refresh(criteria)
        return criteria

    async def get_criteria_map_by_document_ids(
        self,
        doc_ids: List[str],
    ) -> dict[str, Criteria]:
        """
        document_id 리스트로 Criteria를 일괄 조회하여 dict로 반환

        Args:
            doc_ids: 클라우드 문서 ID 목록

        Returns:
            { document_id: Criteria } — 매칭되지 않는 ID는 키에 포함되지 않음
        """
        if not doc_ids:
            return {}
        stmt = select(Criteria).where(Criteria.document_id.in_(doc_ids))
        result = await self.db.execute(stmt)
        return {c.document_id: c for c in result.scalars().all()}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_criteria_repository_alias.py -x`
Expected: PASS — all 4 cases green.

**Step 5: Commit**

```bash
git add app/repositories/criteria_repository.py tests/test_criteria_repository_alias.py
git commit -m "feat(criteria): repo methods for display_alias update and doc-id lookup"
```

---

### Task 4: PATCH `/api/admin/criteria/{id}/display-alias` endpoint

**Specialist:** backend-engineer
**Depends on:** Task 2 (`UpdateDisplayAliasRequest`/`Response` schemas), Task 3 (`update_display_alias` repo method)
**Produces:** Public admin API for alias edits. Returns 200/404/422/401.

**Files:**
- Modify: `app/routers/admin/criteria.py`
- Create: `tests/test_admin_criteria_alias_router.py`

**Step 1: Write the failing test**

```python
# tests/test_admin_criteria_alias_router.py
"""PATCH /api/admin/criteria/{id}/display-alias 테스트"""
import pytest


@pytest.mark.asyncio
async def test_patch_alias_success(admin_client, criteria_factory):
    criteria = await criteria_factory(title="orig.pdf")
    res = await admin_client.patch(
        f"/api/admin/criteria/{criteria.id}/display-alias",
        json={"display_alias": "math-grade-6"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["criteria_id"] == criteria.id
    assert body["display_alias"] == "math-grade-6"


@pytest.mark.asyncio
async def test_patch_alias_clears_with_null(admin_client, criteria_factory):
    criteria = await criteria_factory(title="orig.pdf")
    await admin_client.patch(
        f"/api/admin/criteria/{criteria.id}/display-alias",
        json={"display_alias": "tmp"},
    )
    res = await admin_client.patch(
        f"/api/admin/criteria/{criteria.id}/display-alias",
        json={"display_alias": None},
    )
    assert res.status_code == 200
    assert res.json()["display_alias"] is None


@pytest.mark.asyncio
async def test_patch_alias_not_found(admin_client):
    res = await admin_client.patch(
        "/api/admin/criteria/99999/display-alias",
        json={"display_alias": "x"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_patch_alias_rejects_korean(admin_client, criteria_factory):
    criteria = await criteria_factory(title="orig.pdf")
    res = await admin_client.patch(
        f"/api/admin/criteria/{criteria.id}/display-alias",
        json={"display_alias": "한글"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_alias_requires_admin(authenticated_user_client, criteria_factory):
    criteria = await criteria_factory(title="orig.pdf")
    res = await authenticated_user_client.patch(
        f"/api/admin/criteria/{criteria.id}/display-alias",
        json={"display_alias": "x"},
    )
    assert res.status_code in (401, 403)
```

Reuse the existing admin/user client and factory fixtures from `tests/conftest.py`. If the project uses different fixture names, adapt to whatever `tests/test_admin_criteria_router.py` (or nearest existing admin router test) uses.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_admin_criteria_alias_router.py -x`
Expected: FAIL — `405 Method Not Allowed` or `404`.

**Step 3: Write minimal implementation**

In `app/routers/admin/criteria.py`, add imports:

```python
from app.schemas.criteria import (
    UploadCriteriaResponse,
    DeleteCriteriaResponse,
    DeleteSingleCriteriaResponse,
    UpdateDisplayAliasRequest,
    UpdateDisplayAliasResponse,
)
```

Append a new route handler:

```python
@router.patch(
    "/{criteria_id}/display-alias",
    response_model=UpdateDisplayAliasResponse,
    summary="평가기준 표시명(alias) 업데이트",
    description="DB-only 업데이트. 클라우드 재업로드 없음. "
    "ASCII 문자만 허용. NULL로 보내면 alias 제거.",
)
async def update_display_alias(
    criteria_id: int,
    payload: UpdateDisplayAliasRequest,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        repo = CriteriaRepository(db)
        updated = await repo.update_display_alias(
            criteria_id, payload.display_alias
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="평가기준을 찾을 수 없습니다.",
            )
        await db.commit()
        logger.info(
            f"display_alias 업데이트: admin={current_admin.username}, "
            f"id={criteria_id}, alias={payload.display_alias!r}"
        )
        return UpdateDisplayAliasResponse(
            success=True,
            criteria_id=criteria_id,
            display_alias=updated.display_alias,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"display_alias 업데이트 실패: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="표시명 업데이트 중 오류가 발생했습니다.",
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_admin_criteria_alias_router.py -x`
Expected: PASS — all 5 cases green.

**Step 5: Commit**

```bash
git add app/routers/admin/criteria.py tests/test_admin_criteria_alias_router.py
git commit -m "feat(admin-criteria): PATCH endpoint for display_alias (DB-only)"
```

---

### Task 5: Enrich admin `criteria_list` view

**Specialist:** backend-engineer
**Depends on:** Task 3 (`get_criteria_map_by_document_ids`)
**Produces:**
- `criteria_items.documents[*].display_alias` available to top table.
- `cloud_documents[*]` enriched to `{document_id, display_name, alias, title, criteria_id}` for bottom table.

**Files:**
- Modify: `app/routers/admin/criteria_views.py`
- Create: `tests/test_criteria_list_view.py`

**Step 1: Write the failing test**

```python
# tests/test_criteria_list_view.py
"""평가기준 목록 뷰의 데이터 보강 테스트"""
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_cloud_docs_get_matching_title_and_alias(
    admin_client, criteria_factory
):
    c = await criteria_factory(
        title="orig.pdf",
        document_id="cloud-doc-123",
        status="active",
        display_alias="my-alias",
    )

    fake_list = AsyncMock(return_value=[
        {"document_id": "cloud-doc-123", "display_name": "orig_pdf"},
        {"document_id": "cloud-doc-orphan", "display_name": "orphan_pdf"},
    ])
    with patch(
        "app.routers.admin.criteria_views.CriteriaVectorService.list_criteria_documents",
        fake_list,
    ):
        res = await admin_client.get("/admin/criteria")

    assert res.status_code == 200
    html = res.text
    # 상단 표에 alias가 노출되는지
    assert "my-alias" in html
    # 하단 표에 매칭된 title이 노출되는지
    assert "orig.pdf" in html
    # 고아 문서는 '(매칭 없음)' 으로 표시
    assert "(매칭 없음)" in html
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_criteria_list_view.py -x`
Expected: FAIL — current view does not enrich cloud docs with DB title, and `display_alias` is not in `criteria_items`.

**Step 3: Write minimal implementation**

In `app/routers/admin/criteria_views.py` `criteria_list`, modify the enrichment block:

```python
        # 클라우드 문서 → DB Criteria 매핑
        criteria_repo = CriteriaRepository(db)
        cloud_doc_ids = [d["document_id"] for d in cloud_documents]
        doc_map = await criteria_repo.get_criteria_map_by_document_ids(
            cloud_doc_ids
        )
        cloud_documents = [
            {
                "document_id": d["document_id"],
                "display_name": d.get("display_name"),
                "title": (
                    doc_map[d["document_id"]].title
                    if d["document_id"] in doc_map
                    else None
                ),
                "alias": (
                    doc_map[d["document_id"]].display_alias
                    if d["document_id"] in doc_map
                    else None
                ),
                "criteria_id": (
                    doc_map[d["document_id"]].id
                    if d["document_id"] in doc_map
                    else None
                ),
            }
            for d in cloud_documents
        ]
```

And update the top-table mapping to include `display_alias`:

```python
        criteria_items = {
            "documents": [
                {
                    "id": criteria.id,
                    "title": criteria.title,
                    "display_alias": criteria.display_alias,
                    "status": criteria.status,
                    "file_size": criteria.file_size,
                    "created_at": criteria.created_at,
                    "document_id": criteria.document_id,
                    "cloud_synced": (
                        criteria.document_id is not None
                        and criteria.document_id in cloud_doc_ids_set
                    ),
                }
                for criteria in all_criteria
            ]
        }
```

(Compute `cloud_doc_ids_set = set(cloud_doc_ids)` once.)

The HTML rendering itself is Task 8 — this task only needs to verify the data shape reaches the template. The test will pass once Task 8 is also done; until then, the test assertion on `"my-alias"` may fail. **For Wave 2, mark the test xfail with a TODO referencing Task 8**, OR write a router-level test that asserts the dict shape directly without rendering. Pick whichever fits the project's testing style.

A safer router-only test variant:

```python
# Alternate test focused on data shape, not rendered HTML
async def test_criteria_items_includes_display_alias(...):
    ctx = await render_view_and_capture_context(...)
    assert ctx["criteria"]["documents"][0]["display_alias"] == "my-alias"
    assert ctx["cloud_documents"][0]["title"] == "orig.pdf"
```

Use whichever style the existing view tests use.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_criteria_list_view.py -x`
Expected: PASS for the data-shape assertions.

**Step 5: Commit**

```bash
git add app/routers/admin/criteria_views.py tests/test_criteria_list_view.py
git commit -m "feat(admin-criteria-view): enrich cloud docs with title/alias and expose display_alias on top table"
```

---

### Task 6: Switch user dashboard criteria source to DB with alias fallback

**Specialist:** backend-engineer
**Depends on:** Task 1 (`Criteria.display_alias`)
**Produces:**
- Template variable `criteria_documents = [{"name": <alias or title>, "id": <int>}, ...]` for `templates/user/dashboard.html`.
- Removes cloud-side network call from user dashboard rendering path.

**Files:**
- Modify: `app/routers/views.py`
- Create: `tests/test_user_dashboard_criteria_source.py`

**Step 1: Write the failing test**

```python
# tests/test_user_dashboard_criteria_source.py
"""사용자 대시보드가 alias-or-title 값을 사용하는지 검증"""
import pytest


@pytest.mark.asyncio
async def test_dashboard_uses_alias_when_set(
    authenticated_user_client, criteria_factory
):
    await criteria_factory(
        title="orig.pdf",
        status="active",
        display_alias="readable-name",
    )
    res = await authenticated_user_client.get("/dashboard")
    assert res.status_code == 200
    assert "readable-name" in res.text


@pytest.mark.asyncio
async def test_dashboard_falls_back_to_title_when_alias_null(
    authenticated_user_client, criteria_factory
):
    await criteria_factory(
        title="fallback-doc.pdf",
        status="active",
        display_alias=None,
    )
    res = await authenticated_user_client.get("/dashboard")
    assert "fallback-doc.pdf" in res.text


@pytest.mark.asyncio
async def test_dashboard_does_not_call_cloud(
    authenticated_user_client, criteria_factory, monkeypatch
):
    """클라우드 호출이 제거되었는지 확인"""
    called = {"count": 0}

    async def fake_list(self):
        called["count"] += 1
        return []

    monkeypatch.setattr(
        "app.services.criteria_vector_service.CriteriaVectorService.list_criteria_documents",
        fake_list,
    )
    await criteria_factory(title="x.pdf", status="active")
    await authenticated_user_client.get("/dashboard")
    assert called["count"] == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_user_dashboard_criteria_source.py -x`
Expected: FAIL — the dashboard currently calls `CriteriaVectorService.list_criteria_documents()`.

**Step 3: Write minimal implementation**

In `app/routers/views.py`, replace both call sites (`user_dashboard` and `upload_document`):

Replace:
```python
    criteria_service = CriteriaVectorService()
    criteria_documents = await criteria_service.list_criteria_documents()
```

With:
```python
    from app.db import get_db  # if not imported
    from app.repositories.criteria_repository import CriteriaRepository
    # NOTE: 둘은 이미 함수 시그니처 또는 모듈 임포트로 사용 가능해야 함

    repo = CriteriaRepository(db)
    active_list = await repo.get_active_criteria()
    criteria_documents = [
        {
            "id": c.id,
            "name": c.display_alias or c.title,
        }
        for c in active_list
    ]
```

You will need to add `db: AsyncSession = Depends(get_db)` to `user_dashboard`'s and `upload_document`'s signatures (they currently don't take a DB session).

Remove the now-unused `CriteriaVectorService` import from `views.py` if no other handler in this module needs it. Run `grep -n "CriteriaVectorService" app/routers/views.py` to verify before deleting.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_user_dashboard_criteria_source.py -x`
Expected: PASS — all 3 cases green.

**Step 5: Commit**

```bash
git add app/routers/views.py tests/test_user_dashboard_criteria_source.py
git commit -m "refactor(user-views): use DB for active criteria with alias fallback"
```

---

### Task 7: QnA citation alias fallback

**Specialist:** backend-engineer
**Depends on:** Task 1 (`Criteria.display_alias`)
**Produces:** `criteria_metadata[*].title` reflects `(display_alias or title)` so the viewer's "📋 평가기준" output uses alias when set.

**Files:**
- Modify: `app/services/criteria_context_service.py`
- Create: `tests/test_qna_citation_alias.py`

**Step 1: Write the failing test**

```python
# tests/test_qna_citation_alias.py
"""QnA citation에 alias가 반영되는지 검증"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.criteria_context_service import CriteriaContextService


@pytest.mark.asyncio
async def test_citation_uses_alias_when_set(async_session, criteria_factory):
    await criteria_factory(
        title="lesson-criteria.pdf",
        status="active",
        display_alias="readable-criterion",
    )
    service = CriteriaContextService(db=async_session)

    # search_criteria가 클라우드에서 sanitized title을 돌려주는 상황을 모킹
    fake_search = AsyncMock(return_value={
        "response_text": "answer",
        "citations": [{"title": "lesson-criteria.pdf", "uri": "..."}],
        "sources_count": 1,
    })
    with patch.object(service.vector_service, "search_criteria", fake_search):
        result = await service.get_criteria_context("question")

    assert len(result["criteria_metadata"]) == 1
    assert result["criteria_metadata"][0]["title"] == "readable-criterion"


@pytest.mark.asyncio
async def test_citation_falls_back_when_alias_null(async_session, criteria_factory):
    await criteria_factory(
        title="raw-title.pdf",
        status="active",
        display_alias=None,
    )
    service = CriteriaContextService(db=async_session)
    fake_search = AsyncMock(return_value={
        "response_text": "answer",
        "citations": [{"title": "raw-title.pdf"}],
        "sources_count": 1,
    })
    with patch.object(service.vector_service, "search_criteria", fake_search):
        result = await service.get_criteria_context("question")

    assert result["criteria_metadata"][0]["title"] == "raw-title.pdf"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_qna_citation_alias.py -x`
Expected: FAIL — first test fails because current code emits raw `criteria.title`.

**Step 3: Write minimal implementation**

In `app/services/criteria_context_service.py`, locate the block that builds `criteria_metadata`:

```python
                        if criteria:
                            if criteria.id not in criteria_ids:
                                criteria_ids.append(criteria.id)
                                criteria_metadata.append({
                                    "id": criteria.id,
                                    "title": criteria.title,
                                    "file_path": criteria.file_path
                                })
```

Change `"title": criteria.title` to:

```python
                                    "title": criteria.display_alias or criteria.title,
```

The lookup query `Criteria.title.like(f"%{title}%")` is unchanged — that's the matching key to the cloud-side sanitized title, not the user-facing display string.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_qna_citation_alias.py -x`
Expected: PASS — both cases green.

**Step 5: Commit**

```bash
git add app/services/criteria_context_service.py tests/test_qna_citation_alias.py
git commit -m "feat(qna): citation title uses display_alias fallback"
```

---

### Task 8: Admin criteria_list template — top table sub-line + bottom cloud table

**Specialist:** frontend-engineer
**Depends on:** Task 5 (enriched data: `display_alias` on top, `title`/`alias`/`criteria_id` on bottom)
**Produces:**
- Top table renders `(item.display_alias)` as a secondary sub-line.
- Bottom cloud table renders 3 columns `[평가기준 제목 | 표시 이름 | 문서 ID]` with inline-editable alias cells (`.alias-cell` markup; JS wiring is Task 11).

**Files:**
- Modify: `app/templates/admin/criteria_list.html`

**Step 1: Write the failing test (visual/manual + render-based)**

For a Jinja template change, a useful TDD substitute is a template-rendering assertion. Either use the existing view test from Task 5 (assert specific markup classes/strings in `res.text`) or add a `tests/test_criteria_list_template.py` that does an HTTP GET and asserts:

```python
@pytest.mark.asyncio
async def test_bottom_table_columns_and_alias_cell(
    admin_client, criteria_factory
):
    c = await criteria_factory(
        title="orig.pdf",
        document_id="doc-1",
        status="active",
        display_alias="alias-set",
    )
    with patch_cloud_docs([{"document_id": "doc-1", "display_name": "orig_pdf"}]):
        res = await admin_client.get("/admin/criteria")

    # 헤더 3개
    assert "평가기준 제목" in res.text
    assert "표시 이름" in res.text
    assert "문서 ID" in res.text
    # alias-cell 데이터 속성
    assert 'data-criteria-id="{}"'.format(c.id) in res.text
    assert 'class="alias-cell"' in res.text or 'class=\'alias-cell\'' in res.text
    # 상단 표에 alias 서브라인
    assert "표시명: alias-set" in res.text
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_criteria_list_template.py -x`
Expected: FAIL — bottom-table header still reads `표시 이름` / `문서 ID` only (no `평가기준 제목`), no `.alias-cell` markup, no alias sub-line.

**Step 3: Write minimal implementation**

In `app/templates/admin/criteria_list.html`, the top-table "제목" cell (`<td class="px-6 py-4">` around line 154):

```html
<td class="px-6 py-4">
    <div class="text-sm font-medium text-gray-900">
        {{ item.title }}
    </div>
    {% if item.display_alias %}
    <div class="text-xs text-blue-600 mt-1">
        표시명: {{ item.display_alias }}
    </div>
    {% endif %}
    <div class="text-xs text-gray-500 mt-1">
        ID: {{ item.id }}
    </div>
</td>
```

Replace the entire bottom "클라우드 Store 문서" `<table>` (around lines 327-354) with:

```html
<table class="w-full">
    <thead class="bg-gray-50">
        <tr>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                평가기준 제목
            </th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                표시 이름
            </th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                문서 ID
            </th>
        </tr>
    </thead>
    <tbody class="divide-y divide-gray-200">
        {% for doc in cloud_documents %}
        <tr class="hover:bg-gray-50">
            <td class="px-6 py-4 text-sm text-gray-900">
                {{ doc.title or '(매칭 없음)' }}
            </td>
            <td class="px-6 py-4 text-sm">
                {% if doc.criteria_id %}
                <span class="alias-cell cursor-pointer hover:bg-blue-50 px-2 py-1 rounded"
                      data-criteria-id="{{ doc.criteria_id }}"
                      data-original="{{ doc.alias or '' }}">
                    {{ doc.alias or '(미설정)' }}
                </span>
                {% else %}
                <span class="text-gray-400">-</span>
                {% endif %}
            </td>
            <td class="px-6 py-4 text-xs text-gray-500 font-mono">
                {{ doc.document_id }}
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_criteria_list_template.py -x`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/templates/admin/criteria_list.html tests/test_criteria_list_template.py
git commit -m "feat(admin-criteria-list): alias sub-line + 3-column cloud table with editable cells"
```

---

### Task 9: Admin criteria_detail template — alias display

**Specialist:** frontend-engineer
**Depends on:** Task 5 (template already receives `criteria` ORM object → `criteria.display_alias` available)
**Produces:** Alias rendered on detail page header (read-only display for now; future iteration can add inline edit here too).

**Files:**
- Modify: `app/templates/admin/criteria_detail.html`

**Step 1: Write the failing test**

```python
# Add to tests/test_admin_criteria_views.py (or create tests/test_criteria_detail_template.py)
@pytest.mark.asyncio
async def test_detail_shows_display_alias(admin_client, criteria_factory):
    c = await criteria_factory(
        title="orig.pdf",
        display_alias="detail-alias",
    )
    res = await admin_client.get(f"/admin/criteria/{c.id}")
    assert res.status_code == 200
    assert "표시명: detail-alias" in res.text


@pytest.mark.asyncio
async def test_detail_hides_alias_line_when_null(admin_client, criteria_factory):
    c = await criteria_factory(title="orig.pdf", display_alias=None)
    res = await admin_client.get(f"/admin/criteria/{c.id}")
    assert "표시명:" not in res.text
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_criteria_detail_template.py -x`
Expected: FAIL — no `표시명:` rendering yet.

**Step 3: Write minimal implementation**

In `app/templates/admin/criteria_detail.html`, immediately below the existing `<h1>`/title block (around line 50), insert:

```html
{% if criteria.display_alias %}
<p class="text-sm text-blue-700 mt-1">
    표시명: {{ criteria.display_alias }}
</p>
{% endif %}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_criteria_detail_template.py -x`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/templates/admin/criteria_detail.html tests/test_criteria_detail_template.py
git commit -m "feat(admin-criteria-detail): show display_alias when set"
```

---

### Task 10: User dashboard template — alias-or-title rendering

**Specialist:** frontend-engineer
**Depends on:** Task 6 (`criteria_documents = [{name, id}, ...]`)
**Produces:** End-user dashboard "활성 평가 기준" list shows alias when set, else original title.

**Files:**
- Modify: `app/templates/user/dashboard.html`

**Step 1: Write the failing test**

Use the tests from Task 6 (`test_dashboard_uses_alias_when_set`, `test_dashboard_falls_back_to_title_when_alias_null`) — they assert text rendered in HTML and depend on this template change to pass end-to-end. Add one more focused assertion that pins the specific dictionary key being rendered:

```python
@pytest.mark.asyncio
async def test_dashboard_renders_name_field(
    authenticated_user_client, criteria_factory
):
    await criteria_factory(
        title="title-only.pdf",
        status="active",
        display_alias=None,
    )
    res = await authenticated_user_client.get("/dashboard")
    # 'criteria.display_name' (legacy) 문자열이 더 이상 나오지 않아야 함
    assert "display_name" not in res.text
    assert "title-only.pdf" in res.text
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_user_dashboard_criteria_source.py -x`
Expected: FAIL — template still references `criteria.display_name`.

**Step 3: Write minimal implementation**

In `app/templates/user/dashboard.html` line ~304, replace:

```html
{{ criteria.display_name }}
```

with:

```html
{{ criteria.name }}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_user_dashboard_criteria_source.py -x`
Expected: PASS — all dashboard tests green.

**Step 5: Commit**

```bash
git add app/templates/user/dashboard.html
git commit -m "feat(user-dashboard): render alias-or-title via criteria.name"
```

---

### Task 11: Inline alias edit JS

**Specialist:** frontend-engineer
**Depends on:** Task 4 (PATCH endpoint), Task 8 (`.alias-cell` markup)
**Produces:** Click `.alias-cell` → input → Enter/blur → PATCH → updated cell + toast. Invalid input (non-ASCII) blocked client-side.

**Files:**
- Modify: `app/static/js/criteria_list.js`

**Step 1: Write the failing test**

For DOM/fetch interaction, write a small jsdom-style test if the project already has a JS test runner; otherwise rely on a Playwright-style integration test or a manual checklist captured here. **Manual verification checklist** (must be exercised before commit):

1. Open `/admin/criteria` as admin.
2. Click any `(미설정)` cell in the bottom table — it becomes an `<input>`.
3. Type `valid-alias`, press Enter — cell shows `valid-alias`, toast shows success.
4. Reload page — `valid-alias` persists.
5. Click the cell again, clear the value, press Enter — cell shows `(미설정)`, alias is cleared (verify via DB or by reload).
6. Click another cell, type `한글-alias`, press Enter — toast shows ASCII-only error, cell reverts.
7. Click a cell, type something, press Escape — cell reverts without PATCH.

If the project does have a JS test runner (`package.json` script for `vitest`/`jest`), add a unit test exercising the `updateDisplayAlias` function with a mocked `fetch`. Inspect `package.json` and `tests/` first.

**Step 2: Run test to verify it fails**

If JS unit test exists: run it; expected FAIL.
Otherwise: walk the manual checklist on a fresh page; steps 2–7 fail because handler does not exist.

**Step 3: Write minimal implementation**

Append to `app/static/js/criteria_list.js`:

```javascript
// 평가기준 alias 인라인 편집
function isAsciiOnly(s) {
    return /^[\x00-\x7F]*$/.test(s);
}

async function updateDisplayAlias(criteriaId, newAlias) {
    const payload = newAlias && newAlias.length > 0
        ? { display_alias: newAlias }
        : { display_alias: null };
    const res = await fetch(
        `/api/admin/criteria/${criteriaId}/display-alias`,
        {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }
    );
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return await res.json();
}

function activateAliasEdit(span) {
    const original = span.dataset.original || '';
    const input = document.createElement('input');
    input.type = 'text';
    input.value = original;
    input.maxLength = 255;
    input.className = 'border rounded px-2 py-1 text-sm w-full';

    let finalized = false;

    const restore = (text, cls = '') => {
        const newSpan = document.createElement('span');
        newSpan.className = 'alias-cell cursor-pointer hover:bg-blue-50 px-2 py-1 rounded ' + cls;
        newSpan.dataset.criteriaId = span.dataset.criteriaId;
        newSpan.dataset.original = text;
        newSpan.textContent = text || '(미설정)';
        newSpan.addEventListener('click', () => activateAliasEdit(newSpan));
        input.replaceWith(newSpan);
    };

    const commit = async () => {
        if (finalized) return;
        finalized = true;
        const v = input.value.trim();
        if (v && !isAsciiOnly(v)) {
            alert('ASCII 문자만 허용됩니다.');
            restore(original);
            return;
        }
        try {
            const result = await updateDisplayAlias(
                span.dataset.criteriaId,
                v
            );
            restore(result.display_alias || '');
        } catch (e) {
            alert('업데이트 실패: ' + e.message);
            restore(original);
        }
    };

    const cancel = () => {
        if (finalized) return;
        finalized = true;
        restore(original);
    };

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancel();
        }
    });
    input.addEventListener('blur', commit);

    span.replaceWith(input);
    input.focus();
    input.select();
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.alias-cell').forEach((cell) => {
        cell.addEventListener('click', () => activateAliasEdit(cell));
    });
});
```

**Step 4: Run test to verify it passes**

Walk the full manual checklist again — every step should now pass.

**Step 5: Commit**

```bash
git add app/static/js/criteria_list.js
git commit -m "feat(admin-criteria-list): inline alias edit with ASCII validation"
```

---

## Execution

Plan complete and saved to `docs/plans/2026-05-12-criteria-display-alias.md`.

**Recommended: Agent Team-Driven** — Parallel specialist agents, wave-based execution, two-stage review after each task.

**Alternative: Subagent-Driven** — Serial execution, simpler orchestration, no team overhead. Better if <3 tasks or tasks are tightly coupled.

Which approach?
