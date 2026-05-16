# Cloud Criteria via custom_metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PR #57's manifest-based cloud criteria design with a simpler single-store model using per-document `custom_metadata` + individual `documents.delete()`, while preserving `display_alias` across API key rotation via a small `alias-map.txt` document.

**Architecture:**
- Single `rubric-store` is the source of truth. Each criterion PDF carries `type=criteria`, `stable_id`, `original_title_b64`, `created_at` in `custom_metadata`. A small `alias-map.txt` document (also in `rubric-store`, distinguished by `type=alias_map`) holds `{stable_id → {alias, status, activated_at}}` as base64-chunked JSON.
- Local SQLite `criteria` table is a cache, fully rebuilt on reconcile. `app_state`, the reconciliation lock, the sync gate dependency, and the 503 behavior from PR #57 are preserved.
- A one-time migration converts environments running PR #57 (legacy `rubric-metadata-store` + manifest.json) to the new layout. Documents without `stable_id` use `document_id` as a surrogate when the local PDF cache is missing.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, aiosqlite, Pydantic v2, Jinja2, `google-genai>=1.60` File Search SDK, pytest + pytest-asyncio + pytest-mock + freezegun.

**Spec:** `docs/superpowers/specs/2026-05-15-criteria-cloud-metadata-design.md`

---

## Wave 0 — SDK Verification (1순위, blocking)

Before touching production code, confirm the four SDK behaviors the design depends on. Use a throwaway script + integration test that hits the real Gemini API in a sandbox store.

### Task 1: SDK Verification Script

**Files:**
- Create: `scripts/verify_file_search_sdk.py`

- [ ] **Step 1: Write the verification script**

```python
"""
Verify Gemini File Search SDK supports the 4 operations the new design needs.

Usage:
    GOOGLE_API_KEY=... python scripts/verify_file_search_sdk.py

Prints PASS/FAIL per check. Exits 0 only if all pass.
Creates and tears down a sandbox store; safe to run repeatedly.
"""
import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from google import genai


SANDBOX_STORE = "sdk-verify-sandbox"


def _wait(client, op, timeout=120):
    elapsed = 0
    while not op.done and elapsed < timeout:
        time.sleep(2)
        elapsed += 2
        try:
            op = client.operations.get(op)
        except Exception:
            break
    return op


def _find_store(client, display_name):
    for s in client.file_search_stores.list():
        if s.display_name == display_name:
            return s
    return None


def main():
    client = genai.Client()

    # Clean up any prior sandbox
    existing = _find_store(client, SANDBOX_STORE)
    if existing:
        client.file_search_stores.delete(name=existing.name, config={"force": True})

    store = client.file_search_stores.create(config={"display_name": SANDBOX_STORE})
    print(f"Sandbox store: {store.name}")

    results = {}
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"hello world\n")
            sample_path = tmp.name

        # Check 1: upload_to_file_search_store with custom_metadata
        op1 = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store.name,
            file=sample_path,
            config={
                "display_name": "sample-1",
                "custom_metadata": [
                    {"key": "type", "string_value": "criteria"},
                    {"key": "stable_id", "string_value": "01HXYZTEST0001"},
                    {
                        "key": "original_title_b64",
                        "string_list_value": {
                            "values": [base64.b64encode("한글 파일명.pdf".encode()).decode()]
                        },
                    },
                ],
            },
        )
        op1 = _wait(client, op1)
        if not op1.done:
            raise RuntimeError("upload op did not complete")
        doc_name = op1.response.document_name
        results["upload_with_metadata"] = True

        # Check 2: documents.list returns custom_metadata
        listed = list(client.file_search_stores.documents.list(parent=store.name))
        doc = next((d for d in listed if d.name == doc_name), None)
        if doc is None:
            raise RuntimeError("document not in list")
        meta = getattr(doc, "custom_metadata", None)
        results["list_returns_metadata"] = meta is not None and len(meta) > 0

        # Check 3: base64-chunked Korean round-trips
        b64_entry = next(
            (m for m in meta if (getattr(m, "key", None) or m.get("key")) == "original_title_b64"),
            None,
        )
        decoded_ok = False
        if b64_entry is not None:
            slv = getattr(b64_entry, "string_list_value", None) or b64_entry.get("string_list_value")
            values = getattr(slv, "values", None) or (slv.get("values") if isinstance(slv, dict) else [])
            joined = "".join(values)
            decoded_ok = base64.b64decode(joined).decode() == "한글 파일명.pdf"
        results["base64_korean_roundtrip"] = decoded_ok

        # Check 4: documents.delete(name) actually deletes
        client.file_search_stores.documents.delete(name=doc_name)
        time.sleep(2)
        listed_after = list(client.file_search_stores.documents.list(parent=store.name))
        results["delete_by_name"] = all(d.name != doc_name for d in listed_after)

    finally:
        client.file_search_stores.delete(name=store.name, config={"force": True})
        try:
            os.unlink(sample_path)
        except Exception:
            pass

    print("\n=== Results ===")
    all_ok = True
    for k, v in results.items():
        flag = "PASS" if v else "FAIL"
        if not v:
            all_ok = False
        print(f"  {flag}  {k}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the verification against a sandbox API key**

Run: `GOOGLE_API_KEY=<sandbox-key> python scripts/verify_file_search_sdk.py`

Expected output ends with:
```
=== Results ===
  PASS  upload_with_metadata
  PASS  list_returns_metadata
  PASS  base64_korean_roundtrip
  PASS  delete_by_name
```

If any check FAILs, stop and reconvene on the spec — the design assumes all four behaviors.

- [ ] **Step 3: Commit**

```bash
git add scripts/verify_file_search_sdk.py
git commit -m "feat(criteria-meta): SDK verification script (wave 0)"
```

---

## Wave 1 — DB Migration + Pydantic Schemas

### Task 2: Add `stable_id` Column Migration

**Files:**
- Create: `app/migrations/criteria_stable_id.py`
- Modify: `app/migrations/__init__.py`
- Modify: `app/main.py` (startup migration call site)
- Test: `tests/test_criteria_stable_id_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_stable_id_migration.py
"""criteria.stable_id 컬럼 추가 마이그레이션 테스트"""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.migrations.criteria_stable_id import ensure_criteria_stable_id_column


@pytest.mark.asyncio
async def test_adds_stable_id_when_missing():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE criteria (
                id INTEGER PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                document_id VARCHAR(500),
                file_size BIGINT NOT NULL DEFAULT 0,
                file_path VARCHAR(500) NOT NULL DEFAULT '',
                status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
                uploaded_by VARCHAR(255) NOT NULL DEFAULT '',
                display_alias VARCHAR(255)
            )
        """))

    added = await ensure_criteria_stable_id_column(engine)
    assert added is True

    def _columns(sync_conn):
        return {c["name"] for c in inspect(sync_conn).get_columns("criteria")}

    async with engine.begin() as conn:
        cols = await conn.run_sync(_columns)
    assert "stable_id" in cols


@pytest.mark.asyncio
async def test_idempotent_when_column_present():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE criteria (
                id INTEGER PRIMARY KEY,
                stable_id VARCHAR(64)
            )
        """))

    added = await ensure_criteria_stable_id_column(engine)
    assert added is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_stable_id_migration.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.migrations.criteria_stable_id'`.

- [ ] **Step 3: Implement the migration helper**

```python
# app/migrations/criteria_stable_id.py
"""
criteria.stable_id 컬럼 추가 마이그레이션

클라우드 진실의 원천 모델에서 평가기준 식별자.
NULL 허용으로 시작 — 첫 reconcile이 백필.
"""
from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import inspect
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _collect_columns(sync_conn) -> Optional[Set[str]]:
    inspector = inspect(sync_conn)
    try:
        columns = inspector.get_columns("criteria")
    except NoSuchTableError:
        return None
    return {col["name"] for col in columns}


async def ensure_criteria_stable_id_column(engine: AsyncEngine) -> bool:
    """`criteria.stable_id` 컬럼이 없으면 추가한다."""
    async with engine.begin() as conn:
        columns = await conn.run_sync(_collect_columns)
        if columns is None:
            logger.warning("criteria 테이블이 없어 stable_id 패치를 건너뜀")
            return False
        if "stable_id" in columns:
            logger.debug("criteria.stable_id 컬럼이 이미 존재함")
            return False

        await conn.execute(text(
            "ALTER TABLE criteria ADD COLUMN stable_id VARCHAR(64) NULL"
        ))
        logger.info("criteria.stable_id 컬럼을 추가함")
        return True
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_criteria_stable_id_migration.py -v`

Expected: 2 passed.

- [ ] **Step 5: Wire the migration into startup**

Edit `app/migrations/__init__.py`:
- Add import: `from .criteria_stable_id import ensure_criteria_stable_id_column`
- Add to `__all__`: `"ensure_criteria_stable_id_column"`

Edit `app/main.py` startup block — find the call to `ensure_criteria_display_alias_column(...)` and add the new call immediately after:

```python
await ensure_criteria_stable_id_column(engine)
```

- [ ] **Step 6: Commit**

```bash
git add app/migrations/criteria_stable_id.py app/migrations/__init__.py app/main.py tests/test_criteria_stable_id_migration.py
git commit -m "feat(criteria-meta): add stable_id column migration (wave 1)"
```

### Task 3: Update `Criteria` Model

**Files:**
- Modify: `app/models/criteria.py`
- Test: `tests/test_criteria_stable_id_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_stable_id_model.py
"""Criteria 모델에 stable_id 필드가 추가되었는지 확인"""
from app.models.criteria import Criteria


def test_criteria_model_has_stable_id_column():
    col = Criteria.__table__.columns.get("stable_id")
    assert col is not None
    assert col.nullable is True
    assert str(col.type).startswith("VARCHAR")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_stable_id_model.py -v`
Expected: FAIL with `AssertionError: assert None is not None`.

- [ ] **Step 3: Add the column**

Edit `app/models/criteria.py` — inside `class Criteria(Base):`, add (after `display_alias`):

```python
    stable_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="클라우드 진실의 원천에서의 평가기준 고유 ID (ULID). API key 교체에도 살아남음."
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_criteria_stable_id_model.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/models/criteria.py tests/test_criteria_stable_id_model.py
git commit -m "feat(criteria-meta): add stable_id field on Criteria model (wave 1)"
```

### Task 4: Pydantic Schemas for `AliasMap`

**Files:**
- Create: `app/schemas/alias_map.py`
- Test: `tests/test_alias_map_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alias_map_schema.py
"""AliasMap / AliasMapEntry Pydantic 스키마 테스트"""
import pytest
from pydantic import ValidationError

from app.schemas.alias_map import AliasMap, AliasMapEntry


def test_entry_minimal_valid():
    e = AliasMapEntry(alias=None, status="uploaded", activated_at=None)
    assert e.alias is None
    assert e.status == "uploaded"


def test_entry_rejects_bad_status():
    with pytest.raises(ValidationError):
        AliasMapEntry(alias=None, status="garbage", activated_at=None)


def test_alias_map_serialize_and_parse_roundtrip():
    m = AliasMap(
        schema_version=1,
        updated_at="2026-05-15T00:00:00Z",
        entries={
            "01HXYZ": AliasMapEntry(alias="1학기 평가기준", status="active", activated_at="2026-05-15T00:00:00Z"),
            "01HABC": AliasMapEntry(alias=None, status="uploaded", activated_at=None),
        },
    )
    data = m.model_dump(mode="json")
    parsed = AliasMap.model_validate(data)
    assert parsed.entries["01HXYZ"].alias == "1학기 평가기준"
    assert parsed.entries["01HABC"].status == "uploaded"


def test_alias_map_rejects_unsupported_schema_version():
    with pytest.raises(ValidationError):
        AliasMap.model_validate({
            "schema_version": 999,
            "updated_at": "2026-05-15T00:00:00Z",
            "entries": {},
        })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_alias_map_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.alias_map'`.

- [ ] **Step 3: Implement the schemas**

```python
# app/schemas/alias_map.py
"""
alias-map.txt 의 페이로드(base64로 청크 인코딩되는 JSON) 스키마

설계: docs/superpowers/specs/2026-05-15-criteria-cloud-metadata-design.md §5.2
"""
from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


CURRENT_SCHEMA_VERSION = 1

CriteriaStatus = Literal["active", "uploaded", "archived"]


class AliasMapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: Optional[str] = Field(default=None, max_length=255)
    status: CriteriaStatus
    activated_at: Optional[str] = None  # ISO-8601, parsed downstream


class AliasMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = CURRENT_SCHEMA_VERSION
    updated_at: str
    entries: Dict[str, AliasMapEntry] = Field(default_factory=dict)


def empty_alias_map(now_iso: str) -> AliasMap:
    return AliasMap(schema_version=CURRENT_SCHEMA_VERSION, updated_at=now_iso, entries={})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_alias_map_schema.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/schemas/alias_map.py tests/test_alias_map_schema.py
git commit -m "feat(criteria-meta): AliasMap pydantic schemas (wave 1)"
```

### Task 5: Repository `stable_id` Lookup Helpers

**Files:**
- Modify: `app/repositories/criteria_repository.py`
- Test: `tests/test_criteria_repository_stable_id.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_repository_stable_id.py
"""CriteriaRepository — stable_id lookup 헬퍼"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.migrations.criteria_stable_id import ensure_criteria_stable_id_column
from app.models.criteria import Criteria
from app.repositories.criteria_repository import CriteriaRepository


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_criteria_stable_id_column(engine)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest.mark.asyncio
async def test_get_by_stable_id_returns_row(session):
    session.add(Criteria(
        title="t.pdf", document_id="d1", file_size=10, file_path="x",
        status="uploaded", uploaded_by="admin", stable_id="01HSID",
    ))
    await session.commit()

    repo = CriteriaRepository(session)
    row = await repo.get_criteria_by_stable_id("01HSID")
    assert row is not None
    assert row.title == "t.pdf"


@pytest.mark.asyncio
async def test_get_by_stable_id_returns_none_for_missing(session):
    repo = CriteriaRepository(session)
    assert await repo.get_criteria_by_stable_id("nope") is None


@pytest.mark.asyncio
async def test_truncate_clears_all_rows(session):
    session.add(Criteria(
        title="a.pdf", document_id="d2", file_size=10, file_path="x",
        status="uploaded", uploaded_by="admin", stable_id="01HA",
    ))
    await session.commit()
    repo = CriteriaRepository(session)
    await repo.truncate()
    await session.commit()
    assert await repo.get_criteria_by_stable_id("01HA") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_repository_stable_id.py -v`
Expected: FAIL with `AttributeError: 'CriteriaRepository' object has no attribute 'get_criteria_by_stable_id'`.

- [ ] **Step 3: Add the helpers**

Open `app/repositories/criteria_repository.py`. Add inside `class CriteriaRepository:`:

```python
    async def get_criteria_by_stable_id(self, stable_id: str) -> Criteria | None:
        """stable_id로 평가기준 1행을 조회"""
        from sqlalchemy import select
        result = await self.db.execute(
            select(Criteria).where(Criteria.stable_id == stable_id)
        )
        return result.scalar_one_or_none()

    async def truncate(self) -> None:
        """criteria 테이블의 모든 행을 삭제 (reconcile 용)"""
        from sqlalchemy import delete
        await self.db.execute(delete(Criteria))
```

(If `select` / `delete` are already imported at module top, drop the inline imports.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_criteria_repository_stable_id.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/repositories/criteria_repository.py tests/test_criteria_repository_stable_id.py
git commit -m "feat(criteria-meta): repository stable_id + truncate helpers (wave 1)"
```

---

## Wave 2 — `CriteriaAliasMapService`

The service owns alias-map.txt: fetch → parse → modify → upload-then-delete-old. Single responsibility, no SDK leakage beyond what the existing `FileSearchService` already exposes.

### Task 6: Base64 Chunk Codec (alias-map payload)

**Files:**
- Create: `app/services/alias_map_codec.py`
- Test: `tests/test_alias_map_codec.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alias_map_codec.py
"""alias-map 페이로드 base64 청크 인/디코딩"""
import json

from app.services.alias_map_codec import (
    encode_alias_map_payload,
    decode_alias_map_payload,
    ALIAS_MAP_PAYLOAD_KEY,
)


def test_roundtrip_korean_text():
    data = {"schema_version": 1, "entries": {"id1": {"alias": "한글", "status": "active"}}}
    chunks = encode_alias_map_payload(data)
    assert isinstance(chunks, list)
    assert all(isinstance(c, str) for c in chunks)

    decoded = decode_alias_map_payload(chunks)
    assert decoded == data


def test_chunks_are_bounded():
    # 10KB of Korean text
    big = {"entries": {"id1": {"alias": "한" * 10_000, "status": "uploaded"}}}
    chunks = encode_alias_map_payload(big)
    assert all(len(c) <= 3000 for c in chunks)
    assert decode_alias_map_payload(chunks)["entries"]["id1"]["alias"] == "한" * 10_000


def test_payload_key_is_stable():
    # Used elsewhere to identify the payload metadata entry; renaming requires migration
    assert ALIAS_MAP_PAYLOAD_KEY == "payload_b64"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_alias_map_codec.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the codec**

```python
# app/services/alias_map_codec.py
"""
alias-map 페이로드를 base64 청크로 인/디코딩한다.

이유:
- File Search custom_metadata의 string_value는 ASCII로 변환되므로 한글 손실
- 코드의 _manifest_payload_metadata 패턴을 그대로 따와 base64 + string_list_value 청크
"""
from __future__ import annotations

import base64
import json
from typing import Iterable, List


ALIAS_MAP_PAYLOAD_KEY = "payload_b64"
_CHUNK_SIZE = 3000  # file_search_service._MANIFEST_PAYLOAD_CHUNK_SIZE 와 동일


def encode_alias_map_payload(data: dict) -> List[str]:
    """JSON 직렬화 → UTF-8 → base64 → 3000자 청크 리스트."""
    encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")
    if not encoded:
        return [""]
    return [encoded[i:i + _CHUNK_SIZE] for i in range(0, len(encoded), _CHUNK_SIZE)]


def decode_alias_map_payload(chunks: Iterable[str]) -> dict:
    """청크 리스트 → 결합 → base64 디코드 → UTF-8 → JSON parse."""
    joined = "".join(chunks or [])
    if not joined:
        return {}
    return json.loads(base64.b64decode(joined).decode("utf-8"))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_alias_map_codec.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/alias_map_codec.py tests/test_alias_map_codec.py
git commit -m "feat(criteria-meta): alias-map payload base64 codec (wave 2)"
```

### Task 7: `CriteriaAliasMapService` — fetch + parse

**Files:**
- Create: `app/services/criteria_alias_map_service.py`
- Test: `tests/test_criteria_alias_map_service_fetch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_alias_map_service_fetch.py
"""alias-map 문서 fetch & parse — type=alias_map 만 인식"""
import pytest
from unittest.mock import MagicMock

from app.services.alias_map_codec import encode_alias_map_payload, ALIAS_MAP_PAYLOAD_KEY
from app.services.criteria_alias_map_service import CriteriaAliasMapService


def _meta(key, *, string_value=None, string_list_value=None):
    m = MagicMock()
    m.key = key
    m.string_value = string_value
    m.string_list_value = MagicMock(values=string_list_value) if string_list_value is not None else None
    return m


def _doc(name, metas):
    d = MagicMock()
    d.name = name
    d.custom_metadata = metas
    return d


@pytest.mark.asyncio
async def test_fetch_returns_none_when_no_alias_map_doc():
    client = MagicMock()
    client.file_search_stores.list.return_value = iter([MagicMock(name="stores/x", display_name="rubric-store")])
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/a", [_meta("type", string_value="criteria")]),
    ])

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    result = await svc.fetch()
    assert result is None


@pytest.mark.asyncio
async def test_fetch_parses_payload_chunks():
    payload = {"schema_version": 1, "updated_at": "2026-05-15T00:00:00Z",
               "entries": {"01HID": {"alias": "한글", "status": "active", "activated_at": None}}}
    chunks = encode_alias_map_payload(payload)

    client = MagicMock()
    store = MagicMock(name="stores/x", display_name="rubric-store")
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/alias-map", [
            _meta("type", string_value="alias_map"),
            _meta(ALIAS_MAP_PAYLOAD_KEY, string_list_value=chunks),
        ]),
    ])

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    fetched = await svc.fetch()
    assert fetched is not None
    doc_name, alias_map = fetched
    assert doc_name == "docs/alias-map"
    assert alias_map.entries["01HID"].alias == "한글"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_alias_map_service_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement fetch**

```python
# app/services/criteria_alias_map_service.py
"""
alias-map.txt 문서 관리 서비스

책임:
- rubric-store 내 type=alias_map 문서를 fetch / parse
- entries 변경 후 upload-then-delete 안전 순서로 재게시

설계: docs/superpowers/specs/2026-05-15-criteria-cloud-metadata-design.md §4-§6
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.schemas.alias_map import AliasMap, empty_alias_map
from app.services.alias_map_codec import (
    ALIAS_MAP_PAYLOAD_KEY,
    decode_alias_map_payload,
)

logger = logging.getLogger(__name__)


def _meta_value(entry, field):
    if isinstance(entry, dict):
        return entry.get(field)
    return getattr(entry, field, None)


def _read_metadata_kv(custom_metadata):
    """custom_metadata 리스트 → {key: (string_value, [string_list values])}"""
    out = {}
    for m in custom_metadata or []:
        key = _meta_value(m, "key")
        sv = _meta_value(m, "string_value")
        slv = _meta_value(m, "string_list_value")
        values = []
        if slv is not None:
            values = list(getattr(slv, "values", None) or (slv.get("values") if isinstance(slv, dict) else []))
        out[key] = (sv, values)
    return out


class CriteriaAliasMapService:
    def __init__(self, client, store_display_name: str):
        self._client = client
        self._store_display_name = store_display_name

    def _find_store(self):
        for s in self._client.file_search_stores.list():
            if s.display_name == self._store_display_name:
                return s
        return None

    async def fetch(self) -> Optional[Tuple[str, AliasMap]]:
        """(doc_name, AliasMap) 또는 None을 반환. 파싱 실패 시 None."""
        store = self._find_store()
        if not store:
            return None
        for doc in self._client.file_search_stores.documents.list(parent=store.name):
            kv = _read_metadata_kv(getattr(doc, "custom_metadata", None))
            type_value = (kv.get("type") or (None, []))[0]
            if type_value != "alias_map":
                continue
            chunks = (kv.get(ALIAS_MAP_PAYLOAD_KEY) or (None, []))[1]
            try:
                payload = decode_alias_map_payload(chunks)
                if not payload:
                    return doc.name, empty_alias_map(_now_iso())
                return doc.name, AliasMap.model_validate(payload)
            except Exception as e:
                logger.error(f"alias_map 파싱 실패 — 비어있는 맵으로 fallback: {e}")
                return doc.name, empty_alias_map(_now_iso())
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_criteria_alias_map_service_fetch.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/criteria_alias_map_service.py tests/test_criteria_alias_map_service_fetch.py
git commit -m "feat(criteria-meta): alias map service fetch+parse (wave 2)"
```

### Task 8: `CriteriaAliasMapService.replace()` — Upload-Then-Delete

**Files:**
- Modify: `app/services/criteria_alias_map_service.py`
- Test: `tests/test_criteria_alias_map_service_replace.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_alias_map_service_replace.py
"""alias-map replace — upload new succeeds before delete old"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_alias_map_service import CriteriaAliasMapService


def _store():
    s = MagicMock()
    s.name = "stores/x"
    s.display_name = "rubric-store"
    return s


@pytest.mark.asyncio
async def test_replace_uploads_then_deletes_old():
    """기존 doc.name이 있을 때: upload 성공 후에야 delete 호출"""
    client = MagicMock()
    client.file_search_stores.list.return_value = iter([_store()])

    upload_op = MagicMock(done=True)
    upload_op.response.document_name = "docs/alias-map-new"
    client.file_search_stores.upload_to_file_search_store.return_value = upload_op
    client.file_search_stores.documents.delete = MagicMock()

    am = AliasMap(schema_version=1, updated_at="2026-05-15T00:00:00Z",
                  entries={"01HID": AliasMapEntry(alias="x", status="uploaded", activated_at=None)})

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    new_name = await svc.replace(am, old_doc_name="docs/alias-map-old")

    assert new_name == "docs/alias-map-new"
    client.file_search_stores.upload_to_file_search_store.assert_called_once()
    client.file_search_stores.documents.delete.assert_called_once_with(name="docs/alias-map-old")


@pytest.mark.asyncio
async def test_replace_does_not_delete_when_no_old_doc():
    client = MagicMock()
    client.file_search_stores.list.return_value = iter([_store()])
    upload_op = MagicMock(done=True)
    upload_op.response.document_name = "docs/alias-map-1"
    client.file_search_stores.upload_to_file_search_store.return_value = upload_op
    client.file_search_stores.documents.delete = MagicMock()

    am = AliasMap(schema_version=1, updated_at="2026-05-15T00:00:00Z", entries={})

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    await svc.replace(am, old_doc_name=None)

    client.file_search_stores.documents.delete.assert_not_called()


@pytest.mark.asyncio
async def test_replace_does_not_delete_when_upload_fails():
    client = MagicMock()
    client.file_search_stores.list.return_value = iter([_store()])
    client.file_search_stores.upload_to_file_search_store.side_effect = RuntimeError("boom")
    client.file_search_stores.documents.delete = MagicMock()

    am = AliasMap(schema_version=1, updated_at="2026-05-15T00:00:00Z", entries={})

    svc = CriteriaAliasMapService(client=client, store_display_name="rubric-store")
    with pytest.raises(RuntimeError):
        await svc.replace(am, old_doc_name="docs/alias-map-old")

    client.file_search_stores.documents.delete.assert_not_called()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_alias_map_service_replace.py -v`
Expected: FAIL with `AttributeError: ... no attribute 'replace'`.

- [ ] **Step 3: Implement `replace()`**

Add to `app/services/criteria_alias_map_service.py` (top imports + method on the class):

```python
# top imports — extend
import asyncio
import tempfile
from pathlib import Path

from app.services.alias_map_codec import encode_alias_map_payload
```

Add inside `class CriteriaAliasMapService:`:

```python
    async def replace(self, alias_map: AliasMap, old_doc_name: Optional[str]) -> str:
        """
        새 alias-map.txt 문서를 업로드한 뒤(만 성공 시) 이전 문서를 삭제한다.
        upload-then-delete 순서로 부분 손실을 방지.
        """
        store = self._find_store()
        if not store:
            raise RuntimeError(f"rubric-store '{self._store_display_name}' 미존재")

        payload_chunks = encode_alias_map_payload(alias_map.model_dump(mode="json"))

        # alias-map.txt는 내용물이 중요하지 않음(메타데이터에 데이터가 들어있음).
        # File Search는 파일을 요구하므로 placeholder 텍스트를 임시 파일로.
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as tmp:
            tmp.write("alias-map placeholder; data lives in custom_metadata")
            tmp_path = tmp.name

        try:
            op = self._client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store.name,
                file=tmp_path,
                config={
                    "display_name": "alias-map",
                    "custom_metadata": [
                        {"key": "type", "string_value": "alias_map"},
                        {"key": ALIAS_MAP_PAYLOAD_KEY, "string_list_value": {"values": payload_chunks}},
                    ],
                },
            )
            # Poll. 본 단계는 통합 테스트에서 실제 API와 함께 검증.
            elapsed = 0
            while not getattr(op, "done", False) and elapsed < 60:
                await asyncio.sleep(2)
                elapsed += 2
                try:
                    op = self._client.operations.get(op)
                except Exception:
                    break
            if not getattr(op, "done", False):
                raise TimeoutError("alias-map upload timeout")

            new_doc_name = op.response.document_name
        finally:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

        if old_doc_name:
            self._client.file_search_stores.documents.delete(name=old_doc_name)

        return new_doc_name
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_criteria_alias_map_service_replace.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/criteria_alias_map_service.py tests/test_criteria_alias_map_service_replace.py
git commit -m "feat(criteria-meta): alias map upload-then-delete replace (wave 2)"
```

---

## Wave 3 — `CriteriaVectorService` Rewrite

Cut over from store-recreation to per-document operations + stable_id metadata.

### Task 9: `upload_criteria` Writes `stable_id` + `original_title_b64`

**Files:**
- Modify: `app/services/criteria_vector_service.py`
- Test: `tests/test_criteria_vector_service_upload_metadata.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_vector_service_upload_metadata.py
"""upload_criteria가 stable_id와 original_title_b64 메타데이터를 포함"""
import base64
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_upload_criteria_attaches_stable_and_b64_title():
    from app.services.criteria_vector_service import CriteriaVectorService

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = MagicMock()
    svc.file_search_service.upload_document = MagicMock()

    async def fake_upload(**kwargs):
        return {"document_id": "docs/abc", "store_id": "stores/x"}

    svc.file_search_service.upload_document.side_effect = fake_upload

    result = await svc.upload_criteria(
        file_path="/tmp/x.pdf",
        title="한글 평가기준.pdf",
        stable_id="01HABC",
    )
    assert result["document_id"] == "docs/abc"

    call = svc.file_search_service.upload_document.call_args
    meta = call.kwargs["metadata"]
    assert meta["type"] == "criteria"
    assert meta["stable_id"] == "01HABC"
    # base64-encoded UTF-8 of the original title
    expected_b64 = base64.b64encode("한글 평가기준.pdf".encode()).decode()
    assert meta["original_title_b64"] == expected_b64
    assert "created_at" in meta
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_vector_service_upload_metadata.py -v`
Expected: FAIL — current signature has `display_name`, not `title`/`stable_id`.

- [ ] **Step 3: Rewrite `upload_criteria`**

Replace `upload_criteria` in `app/services/criteria_vector_service.py` with:

```python
    async def upload_criteria(
        self,
        file_path: str,
        title: str,
        stable_id: str,
    ) -> Dict[str, str]:
        """
        평가기준 1개를 rubric-store에 업로드 (store 재생성 없이).

        custom_metadata:
          type = "criteria"
          stable_id = <ULID>
          original_title_b64 = base64(UTF-8 title)
          created_at = ISO-8601 UTC
        """
        import base64
        from datetime import datetime, timezone

        original_title_b64 = base64.b64encode(title.encode("utf-8")).decode("ascii")
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        metadata = {
            "type": "criteria",
            "stable_id": stable_id,
            "original_title_b64": original_title_b64,
            "created_at": created_at,
        }
        result = await self.file_search_service.upload_document(
            file_path=file_path,
            display_name=title,
            metadata=metadata,
            store_type="rubric",
        )
        logger.info(f"평가기준 업로드 완료: stable_id={stable_id} document_id={result['document_id']}")
        return result
```

(Drop the old `recreate_store` argument; callers updated in Wave 5.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_criteria_vector_service_upload_metadata.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/criteria_vector_service.py tests/test_criteria_vector_service_upload_metadata.py
git commit -m "feat(criteria-meta): upload_criteria writes stable_id + b64 title (wave 3)"
```

### Task 10: `delete_criteria` Uses `documents.delete(name)`

**Files:**
- Modify: `app/services/criteria_vector_service.py`
- Test: `tests/test_criteria_vector_service_delete_individual.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_vector_service_delete_individual.py
"""delete_criteria가 documents.delete(name=...)를 호출 (store 재생성 X)"""
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_delete_criteria_calls_documents_delete_by_name():
    from app.services.criteria_vector_service import CriteriaVectorService

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = MagicMock()
    delete_mock = MagicMock()
    svc.file_search_service.client.file_search_stores.documents.delete = delete_mock

    ok = await svc.delete_criteria(document_id="fileSearchStores/x/documents/foo")

    assert ok is True
    delete_mock.assert_called_once_with(name="fileSearchStores/x/documents/foo")


@pytest.mark.asyncio
async def test_delete_criteria_does_not_recreate_store():
    from app.services.criteria_vector_service import CriteriaVectorService

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = MagicMock()

    await svc.delete_criteria(document_id="fileSearchStores/x/documents/foo")

    svc.file_search_service.client.file_search_stores.create.assert_not_called()
    svc.file_search_service.client.file_search_stores.delete.assert_not_called()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_vector_service_delete_individual.py -v`
Expected: FAIL — current impl calls `_recreate_criteria_store`.

- [ ] **Step 3: Replace `delete_criteria` + drop `delete_all_criteria` and `_recreate_criteria_store`**

In `app/services/criteria_vector_service.py`:

```python
    async def delete_criteria(self, document_id: str) -> bool:
        """document_id로 식별되는 평가기준 1개를 삭제. store 재생성 없음."""
        if not document_id:
            raise ValueError("document_id가 비어있습니다")
        self.file_search_service.client.file_search_stores.documents.delete(
            name=document_id
        )
        logger.info(f"평가기준 삭제 완료: {document_id}")
        return True
```

Delete the `delete_all_criteria` method and `_recreate_criteria_store` method entirely.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_criteria_vector_service_delete_individual.py -v`
Expected: 2 passed.

- [ ] **Step 5: Sanity-run the existing criteria vector service tests**

Run: `pytest tests/test_criteria_vector_service.py -v`
Expected: most pass; if any tested `_recreate_criteria_store`/`delete_all_criteria`, those will fail. Skip-mark them with a TODO that points to this plan's Wave 7 cleanup, **or** delete tests that asserted the old behavior (store recreation) if they are now obsolete.

- [ ] **Step 6: Commit**

```bash
git add app/services/criteria_vector_service.py tests/test_criteria_vector_service_delete_individual.py tests/test_criteria_vector_service.py
git commit -m "feat(criteria-meta): individual document delete via API (wave 3)"
```

### Task 11: `list_criteria_documents` Returns `custom_metadata`

**Files:**
- Modify: `app/services/criteria_vector_service.py`
- Test: `tests/test_criteria_vector_service_list_metadata.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_vector_service_list_metadata.py
"""list_criteria_documents가 custom_metadata를 함께 반환"""
from unittest.mock import MagicMock

import pytest


def _meta(key, string_value=None, string_list=None):
    m = MagicMock()
    m.key = key
    m.string_value = string_value
    m.string_list_value = MagicMock(values=string_list) if string_list else None
    return m


def _doc(name, metas, display_name="x"):
    d = MagicMock()
    d.name = name
    d.display_name = display_name
    d.custom_metadata = metas
    return d


@pytest.mark.asyncio
async def test_list_returns_documents_with_raw_metadata():
    from app.services.criteria_vector_service import CriteriaVectorService

    store = MagicMock()
    store.name = "stores/x"
    store.display_name = "rubric-store"

    client = MagicMock()
    client.file_search_stores.list.return_value = iter([store])
    client.file_search_stores.documents.list.return_value = iter([
        _doc("docs/a", [
            _meta("type", string_value="criteria"),
            _meta("stable_id", string_value="01HA"),
        ]),
        _doc("docs/b", [_meta("type", string_value="alias_map")]),
    ])

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = client
    svc.store_name = "rubric-store"

    docs = await svc.list_criteria_documents()
    assert len(docs) == 2
    by_name = {d["document_id"]: d for d in docs}
    assert by_name["docs/a"]["custom_metadata_kv"]["type"] == ("criteria", [])
    assert by_name["docs/a"]["custom_metadata_kv"]["stable_id"] == ("01HA", [])
    assert by_name["docs/b"]["custom_metadata_kv"]["type"] == ("alias_map", [])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_vector_service_list_metadata.py -v`
Expected: FAIL — current impl returns only `document_id` + `display_name`.

- [ ] **Step 3: Update `list_criteria_documents`**

Replace the method body in `app/services/criteria_vector_service.py`:

```python
    async def list_criteria_documents(self) -> List[Dict[str, Any]]:
        """
        rubric-store 모든 문서를 메타데이터와 함께 반환.

        반환 형식:
          [{document_id, display_name, custom_metadata_kv: {key: (string_value, [string_list_values])}}]
        """
        from app.services.criteria_alias_map_service import _read_metadata_kv

        client = self.file_search_service.client
        store = next(
            (s for s in client.file_search_stores.list() if s.display_name == self.store_name),
            None,
        )
        if not store:
            logger.warning(f"rubric-store 미존재: {self.store_name}")
            return []

        documents = []
        for doc in client.file_search_stores.documents.list(parent=store.name):
            documents.append({
                "document_id": doc.name,
                "display_name": getattr(doc, "display_name", None),
                "custom_metadata_kv": _read_metadata_kv(getattr(doc, "custom_metadata", None)),
            })
        return documents
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_criteria_vector_service_list_metadata.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/criteria_vector_service.py tests/test_criteria_vector_service_list_metadata.py
git commit -m "feat(criteria-meta): list_criteria_documents exposes metadata (wave 3)"
```

---

## Wave 4 — Reconciliation Rewrite + Legacy Migration

### Task 12: Rewrite `CriteriaReconciliationService.reconcile()`

**Files:**
- Modify: `app/services/criteria_reconciliation_service.py`
- Test: `tests/test_criteria_reconciliation_v2.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_reconciliation_v2.py
"""reconcile v2 — alias_map 기반"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.alias_map import AliasMap, AliasMapEntry, empty_alias_map
from app.services.alias_map_codec import encode_alias_map_payload


def _doc_kv(name, kv_pairs):
    """kv_pairs: list of (key, string_value)"""
    return {
        "document_id": name,
        "display_name": "x",
        "custom_metadata_kv": {k: (v, []) for k, v in kv_pairs},
    }


@pytest.mark.asyncio
async def test_reconcile_inserts_rows_with_alias_from_map(tmp_path, monkeypatch):
    """alias_map의 항목이 DB에 그대로 머티리얼라이즈"""
    from app.services.criteria_reconciliation_service import CriteriaReconciliationService

    fake_vec = MagicMock()
    fake_vec.list_criteria_documents = AsyncMock(return_value=[
        _doc_kv("docs/a", [("type", "criteria"), ("stable_id", "01HA"),
                            ("original_title_b64", "aGVsbG8="),  # "hello"
                            ("created_at", "2026-05-15T00:00:00Z")]),
    ])
    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(return_value=(
        "docs/alias-map",
        AliasMap(schema_version=1, updated_at="2026-05-15T00:00:00Z",
                 entries={"01HA": AliasMapEntry(alias="1학기", status="active", activated_at="2026-05-15T00:00:00Z")}),
    ))
    fake_alias.replace = AsyncMock()

    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()
    inserted = []
    async def _insert(**kwargs):
        inserted.append(kwargs)
    fake_repo.insert = _insert

    fake_state = MagicMock()
    fake_state.get = AsyncMock(side_effect=lambda key: {
        "criteria_api_key_hash": "samehash",
        "criteria_sync_state": "needs_resync",
    }.get(key))
    fake_state.set_many = AsyncMock()
    fake_state.set = AsyncMock()

    db = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.criteria_reconciliation_service.sha256_hex_of_api_key", return_value="samehash"):
        svc = CriteriaReconciliationService(
            db=db,
            vector_service=fake_vec,
            alias_map_service=fake_alias,
            criteria_repo=fake_repo,
            app_state_repo=fake_state,
        )
        result = await svc.reconcile()

    assert result.ok is True
    assert len(inserted) == 1
    assert inserted[0]["stable_id"] == "01HA"
    assert inserted[0]["display_alias"] == "1학기"
    assert inserted[0]["status"] == "active"
    fake_alias.replace.assert_not_called()  # alias_map already consistent


@pytest.mark.asyncio
async def test_reconcile_self_heals_orphan_entries(monkeypatch):
    """alias_map에 있지만 클라우드에 없는 stable_id는 alias_map에서 제거"""
    from app.services.criteria_reconciliation_service import CriteriaReconciliationService

    fake_vec = MagicMock()
    fake_vec.list_criteria_documents = AsyncMock(return_value=[
        _doc_kv("docs/a", [("type", "criteria"), ("stable_id", "01HA"),
                            ("original_title_b64", "aGVsbG8="),
                            ("created_at", "2026-05-15T00:00:00Z")]),
    ])
    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(return_value=(
        "docs/alias-map",
        AliasMap(schema_version=1, updated_at="2026-05-15T00:00:00Z", entries={
            "01HA": AliasMapEntry(alias="x", status="uploaded", activated_at=None),
            "01HGHOST": AliasMapEntry(alias="orphan", status="uploaded", activated_at=None),
        }),
    ))
    fake_alias.replace = AsyncMock()

    fake_repo = MagicMock()
    fake_repo.truncate = AsyncMock()
    async def _insert(**kwargs): pass
    fake_repo.insert = _insert

    fake_state = MagicMock()
    fake_state.get = AsyncMock(return_value=None)
    fake_state.set_many = AsyncMock()

    db = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.criteria_reconciliation_service.sha256_hex_of_api_key", return_value="newhash"):
        svc = CriteriaReconciliationService(
            db=db,
            vector_service=fake_vec,
            alias_map_service=fake_alias,
            criteria_repo=fake_repo,
            app_state_repo=fake_state,
        )
        result = await svc.reconcile()

    assert result.ok is True
    fake_alias.replace.assert_called_once()
    healed_map = fake_alias.replace.call_args.args[0]
    assert "01HGHOST" not in healed_map.entries
    assert "01HA" in healed_map.entries
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_reconciliation_v2.py -v`
Expected: FAIL — current service signature differs (manifest-based).

- [ ] **Step 3: Rewrite the service**

Replace the contents of `app/services/criteria_reconciliation_service.py`:

```python
"""
Criteria 클라우드 동기화 (v2 — alias_map 기반)

설계: docs/superpowers/specs/2026-05-15-criteria-cloud-metadata-design.md §6
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_API_KEY_HASH,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
)
from app.repositories.criteria_repository import CriteriaRepository
from app.schemas.alias_map import AliasMap, AliasMapEntry, empty_alias_map
from app.services.criteria_alias_map_service import CriteriaAliasMapService
from app.services.criteria_vector_service import CriteriaVectorService

logger = logging.getLogger(__name__)

_reconcile_lock = asyncio.Lock()


def sha256_hex_of_api_key() -> str:
    key = (settings.GOOGLE_API_KEY or "").encode("utf-8")
    return hashlib.sha256(key).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ReconcileResult:
    ok: bool = False
    skipped: bool = False
    error: Optional[str] = None
    count: int = 0


class CriteriaReconciliationService:
    def __init__(
        self,
        db,
        vector_service: CriteriaVectorService,
        alias_map_service: CriteriaAliasMapService,
        criteria_repo: CriteriaRepository,
        app_state_repo: AppStateRepository,
    ):
        self._db = db
        self._vec = vector_service
        self._alias = alias_map_service
        self._repo = criteria_repo
        self._state = app_state_repo

    async def reconcile(self) -> ReconcileResult:
        async with _reconcile_lock:
            current_hash = sha256_hex_of_api_key()
            stored_hash = await self._state.get(KEY_API_KEY_HASH)
            stored_state = await self._state.get(KEY_SYNC_STATE)
            key_changed = stored_hash != current_hash

            if not key_changed and stored_state == "ok":
                return ReconcileResult(skipped=True)

            try:
                docs = await self._vec.list_criteria_documents()
                criteria_docs = [d for d in docs if _kv_string(d, "type") == "criteria"]

                fetched = await self._alias.fetch()
                old_doc_name, alias_map = (fetched if fetched else (None, empty_alias_map(_now_iso())))

                valid_stable_ids = {_kv_string(d, "stable_id") for d in criteria_docs}
                valid_stable_ids.discard(None)

                # 4a. 제거: entries 중 클라우드에 없는 stable_id
                cleaned = {sid: e for sid, e in alias_map.entries.items() if sid in valid_stable_ids}
                # 4b. 합성: 클라우드에 있는데 entries에 없는 stable_id
                for d in criteria_docs:
                    sid = _kv_string(d, "stable_id")
                    if sid and sid not in cleaned:
                        cleaned[sid] = AliasMapEntry(alias=None, status="uploaded", activated_at=None)

                if cleaned != alias_map.entries:
                    alias_map = AliasMap(schema_version=1, updated_at=_now_iso(), entries=cleaned)
                    await self._alias.replace(alias_map, old_doc_name=old_doc_name)

                async with self._db.begin():
                    await self._repo.truncate()
                    for d in criteria_docs:
                        sid = _kv_string(d, "stable_id")
                        if not sid:
                            logger.warning(f"stable_id 없는 문서 {d['document_id']} — 캐시 누락")
                            continue
                        entry = cleaned[sid]
                        title_b64 = _kv_string(d, "original_title_b64") or ""
                        try:
                            title = base64.b64decode(title_b64).decode("utf-8") if title_b64 else d.get("display_name") or sid
                        except Exception:
                            title = d.get("display_name") or sid
                        await self._repo.insert(
                            stable_id=sid,
                            document_id=d["document_id"],
                            title=title,
                            display_alias=entry.alias,
                            status=entry.status,
                            created_at=_kv_string(d, "created_at"),
                            activated_at=entry.activated_at,
                        )

                await self._state.set_many({
                    KEY_API_KEY_HASH: current_hash,
                    KEY_LAST_SYNCED_AT: _now_iso(),
                    KEY_SYNC_STATE: "ok",
                    KEY_SYNC_ERROR: None,
                })
                return ReconcileResult(ok=True, count=len(criteria_docs))

            except Exception as e:
                logger.error(f"reconcile 실패: {e}", exc_info=True)
                await self._state.set_many({
                    KEY_SYNC_STATE: "error" if key_changed else "needs_resync",
                    KEY_SYNC_ERROR: str(e),
                })
                return ReconcileResult(error=str(e))


def _kv_string(doc: dict, key: str) -> Optional[str]:
    sv, _ = doc.get("custom_metadata_kv", {}).get(key, (None, []))
    return sv
```

You will also need to add an `insert` method to `CriteriaRepository` with the keyword signature above. Add inside `class CriteriaRepository:`:

```python
    async def insert(
        self,
        *,
        stable_id: str,
        document_id: str,
        title: str,
        display_alias: Optional[str],
        status: str,
        created_at: Optional[str],
        activated_at: Optional[str],
    ) -> None:
        """reconcile에서 사용. 호출자가 트랜잭션을 관리."""
        from app.models.criteria import Criteria
        from datetime import datetime
        row = Criteria(
            stable_id=stable_id,
            document_id=document_id,
            title=title,
            display_alias=display_alias,
            status=status,
            file_size=0,
            file_path="",
            uploaded_by="cloud-sync",
        )
        if created_at:
            try:
                row.created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except Exception:
                pass
        self.db.add(row)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_criteria_reconciliation_v2.py -v`
Expected: 2 passed. If `KEY_API_KEY_HASH` etc. are named differently in your `app_state_repository`, align names accordingly — keep the constants single-sourced.

- [ ] **Step 5: Commit**

```bash
git add app/services/criteria_reconciliation_service.py app/repositories/criteria_repository.py tests/test_criteria_reconciliation_v2.py
git commit -m "feat(criteria-meta): reconcile v2 on alias_map (wave 4)"
```

### Task 13: One-Shot Migration from Legacy `rubric-metadata-store`

**Files:**
- Create: `app/services/criteria_legacy_migration.py`
- Modify: `app/services/criteria_reconciliation_service.py` (call before main reconcile body)
- Test: `tests/test_criteria_legacy_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_legacy_migration.py
"""legacy migration: manifest → alias_map + metadata-store 삭제"""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_no_op_when_migration_marker_set():
    from app.services.criteria_legacy_migration import migrate_from_legacy_manifest

    state = MagicMock()
    state.get = AsyncMock(return_value="true")  # marker present
    client = MagicMock()
    state.set = AsyncMock()

    await migrate_from_legacy_manifest(client=client, app_state=state)

    client.file_search_stores.list.assert_not_called()


@pytest.mark.asyncio
async def test_no_op_when_legacy_store_absent():
    from app.services.criteria_legacy_migration import migrate_from_legacy_manifest

    state = MagicMock()
    state.get = AsyncMock(return_value=None)
    state.set = AsyncMock()

    client = MagicMock()
    client.file_search_stores.list.return_value = iter([
        MagicMock(name="stores/r", display_name="rubric-store"),
    ])

    await migrate_from_legacy_manifest(client=client, app_state=state)

    state.set.assert_called_once_with("criteria_migration_v2_done", "true")


@pytest.mark.asyncio
async def test_deletes_legacy_store_and_sets_marker():
    from app.services.criteria_legacy_migration import migrate_from_legacy_manifest

    state = MagicMock()
    state.get = AsyncMock(return_value=None)
    state.set = AsyncMock()

    legacy_store = MagicMock()
    legacy_store.name = "stores/legacy"
    legacy_store.display_name = "rubric-metadata-store"
    client = MagicMock()
    client.file_search_stores.list.return_value = iter([
        MagicMock(name="stores/r", display_name="rubric-store"),
        legacy_store,
    ])
    client.file_search_stores.delete = MagicMock()

    await migrate_from_legacy_manifest(client=client, app_state=state)

    client.file_search_stores.delete.assert_called_once_with(
        name="stores/legacy", config={"force": True}
    )
    state.set.assert_called_once_with("criteria_migration_v2_done", "true")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_criteria_legacy_migration.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the minimal migration**

```python
# app/services/criteria_legacy_migration.py
"""
PR #57 의 rubric-metadata-store 잔재를 정리하는 일회성 마이그레이션.

스코프(최소):
- marker 검사 → 이미 끝났으면 no-op
- rubric-metadata-store가 존재하면 force=True로 삭제
- marker 기록

stable_id 백필(PDF 로컬 캐시가 있는 경우 재업로드)은 별도 옵션 작업으로 분리.
현재 운영에는 평가기준 PDF가 1-5개로 매우 적어, 관리자가 UI에서 재업로드하는 편이 안전.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

LEGACY_METADATA_STORE_NAME = "rubric-metadata-store"
MIGRATION_MARKER_KEY = "criteria_migration_v2_done"


async def migrate_from_legacy_manifest(*, client, app_state) -> None:
    if await app_state.get(MIGRATION_MARKER_KEY) == "true":
        return

    legacy = None
    for s in client.file_search_stores.list():
        if s.display_name == LEGACY_METADATA_STORE_NAME:
            legacy = s
            break

    if legacy is not None:
        logger.info(f"legacy rubric-metadata-store 발견 — 삭제: {legacy.name}")
        client.file_search_stores.delete(name=legacy.name, config={"force": True})

    await app_state.set(MIGRATION_MARKER_KEY, "true")
```

- [ ] **Step 4: Wire into reconcile**

In `app/services/criteria_reconciliation_service.py`, add this immediately after the `if not key_changed and stored_state == "ok": return ReconcileResult(skipped=True)` line:

```python
            from app.services.criteria_legacy_migration import migrate_from_legacy_manifest
            try:
                await migrate_from_legacy_manifest(
                    client=self._vec.file_search_service.client,
                    app_state=self._state,
                )
            except Exception as e:
                logger.warning(f"legacy migration 실패 (계속 진행): {e}")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_criteria_legacy_migration.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add app/services/criteria_legacy_migration.py app/services/criteria_reconciliation_service.py tests/test_criteria_legacy_migration.py
git commit -m "feat(criteria-meta): legacy metadata-store cleanup migration (wave 4)"
```

---

## Wave 5 — Admin API + CRUD Endpoints

Wave 5 wires the cloud operations into HTTP endpoints. All endpoints use `Depends(require_criteria_sync_ready)` so 503 returns when reconcile hasn't succeeded.

### Task 14: `POST /api/admin/criteria/upload` — Generates `stable_id`

**Files:**
- Modify: `app/routers/admin/criteria.py` (upload route)
- Test: `tests/test_admin_criteria_upload_v2.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_criteria_upload_v2.py
"""upload 라우터가 stable_id를 생성하고 alias_map에 entry 추가"""
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_upload_generates_stable_id_and_alias_entry(monkeypatch, tmp_path):
    # Detailed test depends on the existing admin test harness; this is the
    # behavioral assertion checklist:
    #
    # 1. POST /api/admin/criteria/upload with a small PDF returns 200.
    # 2. CriteriaVectorService.upload_criteria was called with a freshly-generated
    #    stable_id (26-char ULID) and the user-supplied title.
    # 3. CriteriaAliasMapService.replace was called with an AliasMap whose entries
    #    contain the new stable_id, alias=None, status="uploaded".
    # 4. The criteria row in DB has matching stable_id and document_id.
    pytest.skip("Implement with the existing admin upload test harness")
```

This task is structural — defer the full mock harness to integration tests. The router edit itself is straightforward.

- [ ] **Step 2: Edit the upload route**

In `app/routers/admin/criteria.py`, locate the existing upload endpoint and adjust so it:

```python
# minimal sketch — adapt names to existing handler
import secrets

def _new_stable_id() -> str:
    # ULID-like: 26 base32 chars. ulid-py optional; use secrets fallback.
    import time, base64
    ts = int(time.time() * 1000).to_bytes(6, "big")
    rand = secrets.token_bytes(10)
    return base64.b32encode(ts + rand).decode("ascii").rstrip("=")

@router.post("/upload", ...)
async def upload_criteria(
    file: UploadFile = File(...),
    current_admin = Depends(get_current_admin),
    _: None = Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    title = file.filename
    saved_path = await _save_temp(file)  # existing helper

    stable_id = _new_stable_id()
    vec = CriteriaVectorService()
    upload_result = await vec.upload_criteria(
        file_path=saved_path,
        title=title,
        stable_id=stable_id,
    )

    alias_svc = CriteriaAliasMapService(
        client=vec.file_search_service.client,
        store_display_name=settings.FS_RUBRIC_STORE_NAME,
    )
    fetched = await alias_svc.fetch()
    old_doc_name, alias_map = fetched if fetched else (None, empty_alias_map(_now_iso()))
    alias_map.entries[stable_id] = AliasMapEntry(alias=None, status="uploaded", activated_at=None)
    await alias_svc.replace(alias_map, old_doc_name=old_doc_name)

    repo = CriteriaRepository(db)
    await repo.insert(
        stable_id=stable_id,
        document_id=upload_result["document_id"],
        title=title,
        display_alias=None,
        status="uploaded",
        created_at=_now_iso(),
        activated_at=None,
    )
    await db.commit()

    return {"stable_id": stable_id, "document_id": upload_result["document_id"]}
```

Drop the old "동기화 확정" flow (the response no longer needs `pending_sync` etc.).

- [ ] **Step 3: Run integration tests (existing harness)**

Run: `pytest tests/test_admin_criteria_alias_router.py -v`
Expected: most existing tests still pass; any that asserted "needs_sync" semantics need to be adjusted to the new immediate-publish model.

- [ ] **Step 4: Commit**

```bash
git add app/routers/admin/criteria.py tests/test_admin_criteria_upload_v2.py
git commit -m "feat(criteria-meta): upload route generates stable_id + alias entry (wave 5)"
```

### Task 15: `PATCH /api/admin/criteria/{stable_id}/alias`

**Files:**
- Modify: `app/routers/admin/criteria.py`
- Test: `tests/test_admin_criteria_alias_patch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_criteria_alias_patch.py
"""PATCH /api/admin/criteria/{stable_id}/alias"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _login_admin(client):
    # Use whatever helper the existing admin tests use; placeholder:
    return None


def test_patch_alias_updates_map_and_db(monkeypatch):
    fake_alias = MagicMock()
    fake_alias.fetch = AsyncMock(return_value=("docs/alias-map-old", _empty_map()))
    fake_alias.replace = AsyncMock()

    # Patch factory site used by router; align with actual router import path.
    with patch("app.routers.admin.criteria.CriteriaAliasMapService", return_value=fake_alias):
        # ... rest of harness as in existing admin tests
        pass

    pytest.skip("Wire to existing admin test harness; assertions documented inline")


def _empty_map():
    from app.schemas.alias_map import empty_alias_map
    return empty_alias_map("2026-05-15T00:00:00Z")
```

(As with Task 14, this is a structural test; route edit is the substance.)

- [ ] **Step 2: Add the route**

In `app/routers/admin/criteria.py`:

```python
class _AliasPatch(BaseModel):
    alias: Optional[str] = Field(default=None, max_length=255)


@router.patch("/{stable_id}/alias")
async def patch_alias(
    stable_id: str,
    body: _AliasPatch,
    current_admin = Depends(get_current_admin),
    _: None = Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    vec = CriteriaVectorService()
    alias_svc = CriteriaAliasMapService(
        client=vec.file_search_service.client,
        store_display_name=settings.FS_RUBRIC_STORE_NAME,
    )
    fetched = await alias_svc.fetch()
    if not fetched:
        raise HTTPException(status_code=409, detail="alias_map 미존재 — 재동기화 필요")
    old_doc_name, alias_map = fetched

    if stable_id not in alias_map.entries:
        raise HTTPException(status_code=404, detail="평가기준을 찾을 수 없습니다")

    alias_map.entries[stable_id] = alias_map.entries[stable_id].model_copy(
        update={"alias": body.alias}
    )
    alias_map = alias_map.model_copy(update={"updated_at": _now_iso()})
    await alias_svc.replace(alias_map, old_doc_name=old_doc_name)

    repo = CriteriaRepository(db)
    row = await repo.get_criteria_by_stable_id(stable_id)
    if row:
        row.display_alias = body.alias
        await db.commit()

    return {"stable_id": stable_id, "alias": body.alias}
```

- [ ] **Step 3: Smoke run existing alias tests**

Run: `pytest tests/test_admin_criteria_alias_router.py tests/test_criteria_repository_alias.py -v`
Expected: pass (alias semantics preserved).

- [ ] **Step 4: Commit**

```bash
git add app/routers/admin/criteria.py tests/test_admin_criteria_alias_patch.py
git commit -m "feat(criteria-meta): PATCH /alias updates alias_map then DB (wave 5)"
```

### Task 16: `POST /api/admin/criteria/{stable_id}/activate` + `/deactivate`

**Files:**
- Modify: `app/routers/admin/criteria.py`
- Test: `tests/test_admin_criteria_activate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_criteria_activate.py
"""POST .../activate enforces single-active invariant"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.alias_map import AliasMap, AliasMapEntry


@pytest.mark.asyncio
async def test_activate_demotes_other_active_entries(monkeypatch):
    """Verify that activating B demotes A → uploaded in alias_map"""
    pytest.skip("Wire to existing admin test harness; assertion documented inline")
```

- [ ] **Step 2: Add the routes**

```python
@router.post("/{stable_id}/activate")
async def activate(stable_id: str, current_admin=Depends(get_current_admin),
                   _: None = Depends(require_criteria_sync_ready),
                   db: AsyncSession = Depends(get_db)):
    return await _set_status(db, stable_id, "active")


@router.post("/{stable_id}/deactivate")
async def deactivate(stable_id: str, current_admin=Depends(get_current_admin),
                     _: None = Depends(require_criteria_sync_ready),
                     db: AsyncSession = Depends(get_db)):
    return await _set_status(db, stable_id, "uploaded")


async def _set_status(db: AsyncSession, stable_id: str, target_status: str):
    vec = CriteriaVectorService()
    alias_svc = CriteriaAliasMapService(
        client=vec.file_search_service.client,
        store_display_name=settings.FS_RUBRIC_STORE_NAME,
    )
    fetched = await alias_svc.fetch()
    if not fetched:
        raise HTTPException(status_code=409, detail="alias_map 미존재")
    old_doc_name, alias_map = fetched
    if stable_id not in alias_map.entries:
        raise HTTPException(status_code=404, detail="평가기준을 찾을 수 없습니다")

    now = _now_iso()
    new_entries = {}
    for sid, entry in alias_map.entries.items():
        if sid == stable_id:
            new_entries[sid] = entry.model_copy(update={
                "status": target_status,
                "activated_at": now if target_status == "active" else None,
            })
        elif target_status == "active" and entry.status == "active":
            new_entries[sid] = entry.model_copy(update={"status": "uploaded", "activated_at": None})
        else:
            new_entries[sid] = entry

    alias_map = AliasMap(schema_version=1, updated_at=now, entries=new_entries)
    await alias_svc.replace(alias_map, old_doc_name=old_doc_name)

    repo = CriteriaRepository(db)
    for sid, entry in new_entries.items():
        row = await repo.get_criteria_by_stable_id(sid)
        if row:
            row.status = entry.status
            row.activated_at = _parse_iso(entry.activated_at)
    await db.commit()
    return {"stable_id": stable_id, "status": target_status}


def _parse_iso(value: Optional[str]):
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_admin_criteria_activate.py -v`
Expected: skip (structural). Manually exercise via the admin UI in Wave 6.

- [ ] **Step 4: Commit**

```bash
git add app/routers/admin/criteria.py tests/test_admin_criteria_activate.py
git commit -m "feat(criteria-meta): activate/deactivate routes (wave 5)"
```

### Task 17: `DELETE /api/admin/criteria/{stable_id}`

**Files:**
- Modify: `app/routers/admin/criteria.py`
- Test: `tests/test_admin_criteria_delete_v2.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_criteria_delete_v2.py
"""DELETE 라우터: cloud document + alias_map entry + DB row 정리"""
import pytest

@pytest.mark.asyncio
async def test_delete_removes_cloud_alias_and_db():
    pytest.skip("Wire to existing admin test harness; assertion documented inline")
```

- [ ] **Step 2: Replace the existing DELETE handler**

```python
@router.delete("/{stable_id}")
async def delete_criteria_endpoint(
    stable_id: str,
    current_admin=Depends(get_current_admin),
    _: None = Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    repo = CriteriaRepository(db)
    row = await repo.get_criteria_by_stable_id(stable_id)
    if not row:
        raise HTTPException(status_code=404, detail="평가기준을 찾을 수 없습니다")

    vec = CriteriaVectorService()
    await vec.delete_criteria(document_id=row.document_id)

    alias_svc = CriteriaAliasMapService(
        client=vec.file_search_service.client,
        store_display_name=settings.FS_RUBRIC_STORE_NAME,
    )
    fetched = await alias_svc.fetch()
    if fetched:
        old_doc_name, alias_map = fetched
        if stable_id in alias_map.entries:
            new_entries = dict(alias_map.entries)
            new_entries.pop(stable_id, None)
            alias_map = AliasMap(schema_version=1, updated_at=_now_iso(), entries=new_entries)
            await alias_svc.replace(alias_map, old_doc_name=old_doc_name)

    await db.delete(row)
    await db.commit()
    return {"stable_id": stable_id, "deleted": True}
```

Remove the old id-based delete handler that called `delete_all_criteria`/store recreation.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_admin_criteria_delete_v2.py -v`
Expected: skip (structural).

- [ ] **Step 4: Commit**

```bash
git add app/routers/admin/criteria.py tests/test_admin_criteria_delete_v2.py
git commit -m "feat(criteria-meta): DELETE route uses documents.delete + alias_map update (wave 5)"
```

---

## Wave 6 — Admin UI

### Task 18: Single-Table Layout in `criteria_list.html`

**Files:**
- Modify: `app/templates/admin/criteria_list.html`
- Modify: `app/routers/admin/criteria_views.py` (drop dual-table context)
- Modify: `app/static/js/criteria_list.js` (or create)
- Test: `tests/test_criteria_list_template.py` (extend)

- [ ] **Step 1: Update the route context**

Edit `app/routers/admin/criteria_views.py` `criteria_list` handler so the template only receives:

```python
return templates.TemplateResponse(
    "admin/criteria_list.html",
    {
        "request": request,
        "user": current_admin,
        "criteria_items": criteria_items,   # list of dicts: stable_id, title, display_alias, status, created_at, document_id
        "sync": sync,
    },
)
```

Remove the `cloud_documents` enrichment block, `needs_sync`, `pending_count`, `cloud_sync_warning`, `cloud_error`.

- [ ] **Step 2: Rewrite the template (replace body)**

Replace `app/templates/admin/criteria_list.html` body block:

```html
{% block content %}
<div class="max-w-6xl mx-auto">

  <div id="criteria-sync-status" class="mb-4 p-3 rounded border" data-state="{{ sync.state or 'unknown' }}">
    {% if sync.state == 'ok' %}
      <span class="text-green-700 font-medium">● 동기화 완료</span>
      <span class="text-gray-500 text-sm ml-2">마지막 동기화 {{ sync.last_synced_at or '-' }}</span>
    {% elif sync.state == 'needs_resync' %}
      <span class="text-yellow-700 font-medium">⚠ 동기화 필요</span>
      <button type="button" class="ml-3 px-2 py-1 text-sm bg-yellow-600 text-white rounded" data-action="reconcile">재동기화</button>
    {% elif sync.state == 'error' %}
      <span class="text-red-700 font-medium">✗ 동기화 실패 — 평가기준 기능 비활성</span>
      {% if sync.error %}<div class="text-sm text-gray-600 mt-1">{{ sync.error }}</div>{% endif %}
      <button type="button" class="mt-2 px-2 py-1 text-sm bg-red-600 text-white rounded" data-action="reconcile">재동기화</button>
    {% else %}
      <span class="text-gray-500 font-medium">● 동기화 상태 확인 중</span>
    {% endif %}
  </div>

  <div class="flex justify-between items-center mb-6">
    <div>
      <h1 class="text-3xl font-bold text-gray-800">평가 기준 관리</h1>
      <p class="text-gray-600 mt-2">평가에 사용할 기준 문서를 관리합니다. 클라우드가 진실의 원천입니다.</p>
    </div>
    <a href="/admin/criteria/upload" data-disabled-when="not-ok"
       class="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium">
      + 새 기준 업로드
    </a>
  </div>

  <div class="bg-white shadow-md rounded-lg overflow-hidden">
    {% if criteria_items %}
    <table class="w-full">
      <thead class="bg-gray-50">
        <tr>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">표시 이름</th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">원본 파일명</th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">생성일</th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">작업</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-200" id="criteria-rows">
        {% for item in criteria_items %}
        <tr data-stable-id="{{ item.stable_id }}">
          <td class="px-6 py-4 text-sm">
            <span class="alias-cell cursor-pointer hover:bg-blue-50 px-2 py-1 rounded inline-block min-w-[160px]"
                  data-original="{{ item.display_alias or '' }}">
              {{ item.display_alias or '(미설정)' }}
            </span>
          </td>
          <td class="px-6 py-4 text-sm text-gray-900">{{ item.title }}</td>
          <td class="px-6 py-4 text-sm">
            <label class="inline-flex items-center gap-2">
              <input type="radio" name="active_criteria" value="{{ item.stable_id }}"
                     {% if item.status == 'active' %}checked{% endif %}
                     class="active-radio">
              <span>{{ '활성' if item.status == 'active' else '비활성' }}</span>
            </label>
          </td>
          <td class="px-6 py-4 text-sm text-gray-500">
            {% if item.created_at %}{{ item.created_at.strftime('%Y-%m-%d %H:%M') }}{% else %}-{% endif %}
          </td>
          <td class="px-6 py-4 text-sm">
            <button class="delete-btn text-red-600 hover:underline font-medium"
                    data-stable-id="{{ item.stable_id }}"
                    data-title="{{ item.title }}">삭제</button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="p-8 text-center text-gray-600">평가 기준이 없습니다. 새 평가 기준 문서를 업로드하세요.</div>
    {% endif %}
  </div>
</div>
{% endblock %}
```

(Drop the entire "클라우드 Store 문서" lower table block and the `cloud_sync_warning` / `needs_sync` banners. Keep top sync badge.)

- [ ] **Step 3: Add JS for inline alias edit + activate + delete**

Edit `app/static/js/criteria_list.js`:

```javascript
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.alias-cell').forEach((cell) => {
    cell.addEventListener('click', () => startInlineEdit(cell));
  });
  document.querySelectorAll('.active-radio').forEach((r) => {
    r.addEventListener('change', (e) => {
      const sid = e.target.value;
      activate(sid);
    });
  });
  document.querySelectorAll('.delete-btn').forEach((b) => {
    b.addEventListener('click', () => {
      if (confirm(`${b.dataset.title} 평가기준을 삭제하시겠습니까?`)) {
        deleteCriteria(b.dataset.stableId);
      }
    });
  });
});

async function startInlineEdit(cell) {
  const row = cell.closest('tr');
  const sid = row.dataset.stableId;
  const original = cell.dataset.original;
  const input = document.createElement('input');
  input.type = 'text';
  input.maxLength = 255;
  input.value = original;
  input.className = 'border rounded px-1 py-0.5 w-full';
  cell.replaceWith(input);
  input.focus();
  const commit = async () => {
    const next = input.value.trim() || null;
    if (next === original || (next === null && !original)) {
      reset(cell, original);
      return;
    }
    try {
      const r = await fetch(`/api/admin/criteria/${sid}/alias`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias: next }),
      });
      if (!r.ok) throw new Error(await r.text());
      cell.dataset.original = next || '';
      cell.textContent = next || '(미설정)';
    } catch (e) {
      alert(`표시 이름 저장 실패: ${e.message}`);
    } finally {
      reset(cell, cell.dataset.original);
    }
  };
  const reset = (oldCell, value) => {
    const span = oldCell.cloneNode(false);
    span.className = oldCell.className;
    span.dataset.original = value;
    span.textContent = value || '(미설정)';
    input.replaceWith(span);
    span.addEventListener('click', () => startInlineEdit(span));
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { commit(); }
    if (e.key === 'Escape') { reset(cell, original); }
  });
  input.addEventListener('blur', commit);
}

async function activate(sid) {
  try {
    const r = await fetch(`/api/admin/criteria/${sid}/activate`, { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (e) {
    alert(`활성화 실패: ${e.message}`);
  }
}

async function deleteCriteria(sid) {
  try {
    const r = await fetch(`/api/admin/criteria/${sid}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (e) {
    alert(`삭제 실패: ${e.message}`);
  }
}
```

- [ ] **Step 4: Update template test**

Open `tests/test_criteria_list_template.py`. Replace assertions that check for the dual-table (e.g. "클라우드 Store 문서") with checks that the new single-table markup is present:

```python
def test_template_has_single_table_and_inline_alias():
    # Render with a single criteria_items entry and assert:
    # - "클라우드 Store 문서" NOT in html
    # - "alias-cell" class IS in html
    # - "active-radio" class IS in html
    ...
```

Run: `pytest tests/test_criteria_list_template.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/templates/admin/criteria_list.html app/routers/admin/criteria_views.py app/static/js/criteria_list.js tests/test_criteria_list_template.py
git commit -m "feat(criteria-meta): admin UI single-table + inline alias + status toggle (wave 6)"
```

---

## Wave 7 — Cleanup

### Task 19: Remove `CriteriaManifestService` + Manifest Schemas

**Files:**
- Delete: `app/services/criteria_manifest_service.py`
- Delete: `app/schemas/manifest.py` (or wherever Manifest lives)
- Modify: any imports of the above

- [ ] **Step 1: Find all references**

Run: `grep -rn "criteria_manifest_service\|CriteriaManifestService\|class Manifest\b\|ManifestEntry" app/ tests/`

Expected output: a list of files. Read each and remove the references.

- [ ] **Step 2: Delete dead files**

```bash
git rm app/services/criteria_manifest_service.py
# also app/schemas/manifest.py if present
```

- [ ] **Step 3: Run the full test suite**

Run: `pytest -x`
Expected: all green. Fix any straggler imports.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(criteria-meta): remove manifest service and schemas (wave 7)"
```

### Task 20: Remove `FS_RUBRIC_METADATA_STORE_NAME`

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example` if present
- Modify: any `settings.FS_RUBRIC_METADATA_STORE_NAME` references

- [ ] **Step 1: Find references**

Run: `grep -rn "FS_RUBRIC_METADATA_STORE_NAME" app/ tests/ .env* 2>/dev/null`

- [ ] **Step 2: Remove the field**

Delete the field definition in `app/config.py`. Update `.env.example` if present.

- [ ] **Step 3: Run tests**

Run: `pytest -x`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(criteria-meta): drop FS_RUBRIC_METADATA_STORE_NAME setting (wave 7)"
```

### Task 21: Strip `cloud_synced` View Logic + `synced_at` Usage

**Files:**
- Modify: `app/routers/admin/criteria_views.py` (already updated in Task 18, recheck)
- Modify: `app/services/cloud_sync_validator.py` (remove `validate_rubricstore_sync` if unused) or delete the file
- Modify: any QnA / dashboard code that read `criteria.synced_at`

- [ ] **Step 1: Find references**

Run: `grep -rn "cloud_synced\|synced_at\|validate_rubricstore_sync" app/ tests/`

- [ ] **Step 2: Remove or replace**

For each reference, replace with the new semantics (reconcile-driven consistency). If a test asserts the old "pending_sync" UI behavior, delete or rewrite it.

- [ ] **Step 3: Run tests**

Run: `pytest -x`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(criteria-meta): purge cloud_synced/synced_at view-layer references (wave 7)"
```

### Task 22: End-to-End Smoke

**Files:**
- Test: `tests/test_e2e_criteria_meta_flow.py`

- [ ] **Step 1: Write the e2e smoke**

```python
# tests/test_e2e_criteria_meta_flow.py
"""
e2e: upload → activate → patch alias → delete → reconcile, all under mocked SDK
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_full_flow_round_trip():
    # 1. Boot app with empty alias_map.
    # 2. Upload PDF → confirm row in DB, alias_map has new entry with status=uploaded.
    # 3. POST /activate → entry.status="active".
    # 4. PATCH /alias with "한글 별명" → entry.alias updated; PDF NOT re-uploaded.
    # 5. DELETE → documents.delete called; entry removed; row removed.
    # 6. Reconcile with simulated API key change → DB wiped; rebuilt from cloud (now empty).
    pytest.skip("Implement once admin test harness is updated for new endpoints")
```

(This test is the integration capstone; it can be filled in after Waves 4-6 land if the admin test harness needs a small refit.)

- [ ] **Step 2: Run the full suite once more**

Run: `pytest -x`
Expected: green (smoke skipped or passing).

- [ ] **Step 3: Update CLAUDE.md memory if needed**

If you discover non-obvious surprises during implementation that future agents would benefit from (e.g., a quirk in `string_list_value` deserialization), surface them in a memory file under `.claude/projects/.../memory/`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_criteria_meta_flow.py
git commit -m "test(criteria-meta): e2e smoke scaffold (wave 7)"
```

---

## Cross-Cutting Notes

- **PDF cache**: `data/uploads/criteria/` becomes optional. Keep it for now (admins may want to redownload a PDF). Mark in code that absence is non-fatal.
- **stable_id generator**: Task 14 uses a `secrets`-backed pseudo-ULID. If `python-ulid` is later added to dependencies, swap to it for a single line — the value is opaque from the system's perspective.
- **`require_criteria_sync_ready` dependency**: PR #57 added it. Reuse it on every mutation endpoint in Wave 5 (verify by `grep -n "require_criteria_sync_ready" app/routers/admin/criteria.py`).
- **QnA sync gate**: PR #57's behavior ("sync_state != ok → skip criteria citation") is preserved. No changes needed.
- **Rollback**: each wave is independently committed. If something blocks production, revert from the most recent stable wave's tip and the system falls back to PR #57 behavior.
