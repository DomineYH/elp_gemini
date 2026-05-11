# Admin Bulk Export Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use agent-team-driven-development to execute this plan.

**Goal:** 관리자가 전체 사용자의 수집 데이터(분석 보고서·QnA 대화·원본 지도안·메타데이터)를 신분·지역·경력·기간·사용자 필터로 골라 단일 ZIP 스트림으로 다운로드한다.

**Architecture:** FastAPI `StreamingResponse` + `zipfile` (stdlib) 기반 동기 스트리밍 ZIP. 관리자 라우터 `/admin/api/exports/all.zip` 단일 엔드포인트가 `AdminExportService`에 위임. 서비스는 (1) 비동기 SQLAlchemy로 사용자·자원 메타를 한 번에 수집하고 (2) 동기 제너레이터로 ZIP 바이트를 yield. 보고서는 `reports/`, 대화는 `conversations/`, 원본 지도안은 `lessonplans/` 최상위 폴더로 분리하고 `manifest.csv`가 마스터 인덱스 역할을 한다.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x (async), pytest + pytest-asyncio + httpx TestClient, stdlib `zipfile`/`csv`/`hashlib`/`io`. 신규 외부 의존성 0.

---

## Wave Analysis

### Specialists

| Role | Expertise | Tasks |
|------|-----------|-------|
| backend-engineer | Python, FastAPI, SQLAlchemy async, pytest | Tasks 1, 2, 3, 5 |
| frontend-engineer | Jinja2 템플릿, 바닐라 JS, Tailwind | Task 4 |

### Waves

**Wave 1: Foundations** — 순수 함수 / 데이터 스키마. DB·파일 I/O 없음.
- Task 1 (backend-engineer) — 파일명 prefix·슬러그 정규화 헬퍼 + 단위 테스트
- Task 2 (backend-engineer) — `ExportFilters` Pydantic 스키마 + `parse_filters` Depends + 단위 테스트

  *Parallel-safe because:* 두 task는 서로 다른 모듈(`app/utils/admin_export_naming.py` vs `app/schemas/admin_export.py`)을 만들고 import 관계가 없다. 둘 다 외부 함수 시그니처가 본 plan에서 고정돼 있어 wave 2가 양쪽 산출물을 import하기만 하면 된다.

**Wave 2: Core builds** — Wave 1의 헬퍼·스키마 위에 서비스 본체와 UI를 동시에 구축.
- Task 3 (backend-engineer) — `AdminExportService` 비동기 수집기 + CSV/README 빌더
- Task 4 (frontend-engineer) — 관리자 대시보드 내보내기 버튼·모달 + 사용자 상세 페이지 링크

  *Parallel-safe because:* Task 3은 `app/services/admin_export_service.py`만 생성, Task 4는 `app/templates/admin/*.html` 2개만 수정. 파일 교집합 없음. UI는 엔드포인트 URL과 쿼리 파라미터 스펙(본 plan의 Task 5 명세)만 알면 되며 백엔드 구현이 끝나지 않아도 만들 수 있다.
  *Depends on Wave 1:* Task 3은 Task 1의 `build_filename_prefix`·`normalize_profile_fields`와 Task 2의 `ExportFilters`를 import. Task 4는 Wave 1 산출물에 직접 의존하지 않는다 (스펙 기반).

**Wave 3: Streaming + Endpoint** — Wave 2의 서비스를 ZIP으로 출력하고 라우터/메인 앱에 연결.
- Task 5 (backend-engineer) — ZIP 스트리머·`/admin/api/exports/all.zip` 라우터·main.py 등록·통합 테스트

  *Depends on Wave 2:* Task 3의 `AdminExportService.collect()`·CSV 빌더가 반환하는 `ExportPlan` 구조를 그대로 받아 스트림으로 직렬화. Task 4의 UI가 호출하는 엔드포인트를 실제로 구현.

### Dependency Graph

```
Task 1 ─┐
        ├──→ Task 3 ──┐
Task 2 ─┘             ├──→ Task 5
        Task 4 ───────┘
        (spec only)
```

---

## Tasks

### Task 1: Filename Prefix & Profile Normalization Helpers

**Specialist:** backend-engineer
**Depends on:** None
**Produces:** `app/utils/admin_export_naming.py` exposing:
- `normalize_profile_fields(role: str, profile: UserProfile | None, email: str | None) -> NormalizedProfile`
- `build_filename_prefix(user_id: int, profile: NormalizedProfile) -> str`
- `slugify_email(email: str | None) -> str`
- `slugify_original_name(name: str) -> str`
- `NormalizedProfile` dataclass with fields: `role_code: str, region_slug: str, tenure: str, tenure_kind: str, email_slug: str`

**Files:**
- Create: `app/utils/admin_export_naming.py`
- Create: `tests/unit/test_admin_export_naming.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_admin_export_naming.py
import pytest
from app.utils.admin_export_naming import (
    NormalizedProfile,
    build_filename_prefix,
    normalize_profile_fields,
    slugify_email,
    slugify_original_name,
)


class _ProfileStub:
    def __init__(self, **kwargs):
        self.role = kwargs.get("role")
        self.teacher_region = kwargs.get("teacher_region")
        self.teacher_career_years = kwargs.get("teacher_career_years")
        self.preservice_university_region = kwargs.get(
            "preservice_university_region"
        )
        self.preservice_grade = kwargs.get("preservice_grade")


def test_normalize_teacher_full_fields():
    profile = _ProfileStub(
        role="teacher",
        teacher_region="서울",
        teacher_career_years=12,
    )
    out = normalize_profile_fields(
        "teacher", profile, "kim@example.com"
    )
    assert out.role_code == "T"
    assert out.region_slug == "서울"
    assert out.tenure == "12"
    assert out.tenure_kind == "years"
    assert out.email_slug == "kim_at_example_com"


def test_normalize_preservice_full_fields():
    profile = _ProfileStub(
        role="preservice_teacher",
        preservice_university_region="부산",
        preservice_grade=3,
    )
    out = normalize_profile_fields(
        "preservice_teacher", profile, "lee@x.co.kr"
    )
    assert out.role_code == "P"
    assert out.region_slug == "부산"
    assert out.tenure == "3"
    assert out.tenure_kind == "grade"
    assert out.email_slug == "lee_at_x_co_kr"


def test_normalize_missing_profile_uses_defaults():
    out = normalize_profile_fields(
        "teacher", profile=None, email=None
    )
    assert out.role_code == "T"
    assert out.region_slug == "미상"
    assert out.tenure == "NA"
    assert out.tenure_kind == "years"
    assert out.email_slug == "noemail"


def test_normalize_unknown_role_falls_back_to_U():
    out = normalize_profile_fields("admin", None, "a@b.com")
    assert out.role_code == "U"
    assert out.tenure_kind == "years"


def test_build_filename_prefix_teacher():
    profile = NormalizedProfile(
        role_code="T",
        region_slug="서울",
        tenure="12",
        tenure_kind="years",
        email_slug="kim_at_example_com",
    )
    assert (
        build_filename_prefix(42, profile)
        == "T-서울-12y__u00042__kim_at_example_com"
    )


def test_build_filename_prefix_preservice():
    profile = NormalizedProfile(
        role_code="P",
        region_slug="부산",
        tenure="3",
        tenure_kind="grade",
        email_slug="lee_at_x_co_kr",
    )
    assert (
        build_filename_prefix(43, profile)
        == "P-부산-G3__u00043__lee_at_x_co_kr"
    )


def test_build_filename_prefix_missing_tenure():
    profile = NormalizedProfile(
        role_code="T",
        region_slug="미상",
        tenure="NA",
        tenure_kind="years",
        email_slug="noemail",
    )
    assert (
        build_filename_prefix(7, profile)
        == "T-미상-NA__u00007__noemail"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("kim@example.com", "kim_at_example_com"),
        ("LEE.K@X.CO.KR", "lee_k_at_x_co_kr"),
        ("plus+tag@host.io", "plus_tag_at_host_io"),
        (None, "noemail"),
        ("", "noemail"),
    ],
)
def test_slugify_email(raw, expected):
    assert slugify_email(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1학년_수업지도안.pdf", "1학년_수업지도안.pdf"),
        ("path/with/slash.pdf", "path_with_slash.pdf"),
        ("back\\slash:colon*star?.md", "back_slash_colon_star_.md"),
        ("  leading_trail  ", "leading_trail"),
        ("", "untitled"),
    ],
)
def test_slugify_original_name(raw, expected):
    assert slugify_original_name(raw) == expected
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_admin_export_naming.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.utils.admin_export_naming'`

**Step 3: Write minimal implementation**

```python
# app/utils/admin_export_naming.py
"""관리자 일괄 내보내기에서 사용하는 파일명/슬러그 정규화 헬퍼.

순수 함수만 둔다. DB 세션/외부 I/O 의존 없음.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_FORBIDDEN_FILENAME_CHARS = re.compile(r"[\\/:*?\"<>|]+")
_EMAIL_SAFE_CHARS = re.compile(r"[^a-z0-9_]+")
_COLLAPSE_UNDERSCORES = re.compile(r"_+")


@dataclass(frozen=True)
class NormalizedProfile:
    role_code: str
    region_slug: str
    tenure: str
    tenure_kind: str  # "years" | "grade"
    email_slug: str


def slugify_email(email: str | None) -> str:
    if not email:
        return "noemail"
    lowered = email.lower().replace("@", "_at_").replace(".", "_")
    slug = _EMAIL_SAFE_CHARS.sub("_", lowered)
    slug = _COLLAPSE_UNDERSCORES.sub("_", slug).strip("_")
    return slug or "noemail"


def slugify_original_name(name: str | None) -> str:
    if not name:
        return "untitled"
    cleaned = _FORBIDDEN_FILENAME_CHARS.sub("_", name).strip()
    return cleaned or "untitled"


def normalize_profile_fields(
    role: str | None,
    profile,
    email: str | None,
) -> NormalizedProfile:
    role_code, tenure_kind = _role_code_and_tenure_kind(role)
    region_slug = _region_for(role, profile)
    tenure = _tenure_for(role, profile)
    return NormalizedProfile(
        role_code=role_code,
        region_slug=region_slug,
        tenure=tenure,
        tenure_kind=tenure_kind,
        email_slug=slugify_email(email),
    )


def build_filename_prefix(
    user_id: int, profile: NormalizedProfile
) -> str:
    tenure_token = _format_tenure_token(profile)
    return (
        f"{profile.role_code}-{profile.region_slug}-{tenure_token}"
        f"__u{user_id:05d}__{profile.email_slug}"
    )


# ----- internal helpers -----


def _role_code_and_tenure_kind(role: str | None) -> tuple[str, str]:
    if role == "teacher":
        return "T", "years"
    if role == "preservice_teacher":
        return "P", "grade"
    return "U", "years"


def _region_for(role: str | None, profile) -> str:
    if profile is None:
        return "미상"
    if role == "teacher":
        value = getattr(profile, "teacher_region", None)
    elif role == "preservice_teacher":
        value = getattr(profile, "preservice_university_region", None)
    else:
        value = None
    if not value:
        return "미상"
    return slugify_original_name(value)


def _tenure_for(role: str | None, profile) -> str:
    if profile is None:
        return "NA"
    if role == "teacher":
        value = getattr(profile, "teacher_career_years", None)
    elif role == "preservice_teacher":
        value = getattr(profile, "preservice_grade", None)
    else:
        value = None
    if value is None:
        return "NA"
    return str(value)


def _format_tenure_token(profile: NormalizedProfile) -> str:
    if profile.tenure == "NA":
        return "NA"
    if profile.tenure_kind == "years":
        return f"{profile.tenure}y"
    return f"G{profile.tenure}"
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_admin_export_naming.py -v`
Expected: PASS (14 tests)

**Step 5: Commit**

```bash
git add app/utils/admin_export_naming.py tests/unit/test_admin_export_naming.py
git commit -m "feat(admin-export): add filename/profile normalization helpers"
```

---

### Task 2: ExportFilters Schema & parse_filters Dependency

**Specialist:** backend-engineer
**Depends on:** None
**Produces:** `app/schemas/admin_export.py` exposing:
- `ExportFilters` Pydantic model with: `date_from: date|None, date_to: date|None, user_ids: list[int]|None, role: Literal["teacher","preservice_teacher"]|None, region: str|None, include: frozenset[str]`
- `parse_filters() -> ExportFilters` FastAPI dependency callable
- `INCLUDE_KINDS = frozenset({"reports","conversations","lessonplans","meta"})`

**Files:**
- Create: `app/schemas/admin_export.py`
- Create: `tests/unit/test_admin_export_filters.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_admin_export_filters.py
from datetime import date

import pytest
from fastapi import HTTPException

from app.schemas.admin_export import (
    INCLUDE_KINDS,
    ExportFilters,
    parse_filters,
)


def test_parse_filters_defaults():
    f = parse_filters()
    assert isinstance(f, ExportFilters)
    assert f.date_from is None
    assert f.date_to is None
    assert f.user_ids is None
    assert f.role is None
    assert f.region is None
    assert f.include == INCLUDE_KINDS


def test_parse_filters_full():
    f = parse_filters(
        date_from="2026-01-01",
        date_to="2026-03-31",
        user_ids="1,2,42",
        role="teacher",
        region="서울",
        include="reports,meta",
    )
    assert f.date_from == date(2026, 1, 1)
    assert f.date_to == date(2026, 3, 31)
    assert f.user_ids == [1, 2, 42]
    assert f.role == "teacher"
    assert f.region == "서울"
    assert f.include == frozenset({"reports", "meta"})


def test_parse_filters_invalid_date():
    with pytest.raises(HTTPException) as exc:
        parse_filters(date_from="2026-13-99")
    assert exc.value.status_code == 400
    assert "date_from" in exc.value.detail


def test_parse_filters_inverted_range():
    with pytest.raises(HTTPException) as exc:
        parse_filters(date_from="2026-05-01", date_to="2026-04-30")
    assert exc.value.status_code == 400
    assert "date_from must be <= date_to" in exc.value.detail


def test_parse_filters_invalid_user_ids():
    with pytest.raises(HTTPException) as exc:
        parse_filters(user_ids="1,abc,3")
    assert exc.value.status_code == 400
    assert "user_ids" in exc.value.detail


def test_parse_filters_invalid_role():
    with pytest.raises(HTTPException) as exc:
        parse_filters(role="ghost")
    assert exc.value.status_code == 400


def test_parse_filters_unknown_include_token():
    with pytest.raises(HTTPException) as exc:
        parse_filters(include="reports,evil")
    assert exc.value.status_code == 400
    assert "include" in exc.value.detail


def test_parse_filters_empty_user_ids_becomes_none():
    f = parse_filters(user_ids="")
    assert f.user_ids is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_admin_export_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.admin_export'`

**Step 3: Write minimal implementation**

```python
# app/schemas/admin_export.py
"""관리자 일괄 내보내기 쿼리 파라미터 스키마."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict


INCLUDE_KINDS = frozenset(
    {"reports", "conversations", "lessonplans", "meta"}
)
_ALLOWED_ROLES = {"teacher", "preservice_teacher"}


class ExportFilters(BaseModel):
    model_config = ConfigDict(frozen=True)

    date_from: date | None = None
    date_to: date | None = None
    user_ids: list[int] | None = None
    role: Literal["teacher", "preservice_teacher"] | None = None
    region: str | None = None
    include: frozenset[str] = INCLUDE_KINDS


def parse_filters(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    user_ids: str | None = Query(default=None),
    role: str | None = Query(default=None),
    region: str | None = Query(default=None),
    include: str | None = Query(default=None),
) -> ExportFilters:
    parsed_from = _parse_date(date_from, "date_from")
    parsed_to = _parse_date(date_to, "date_to")
    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise HTTPException(
            status_code=400,
            detail="date_from must be <= date_to",
        )

    parsed_ids = _parse_user_ids(user_ids)
    parsed_role = _parse_role(role)
    parsed_include = _parse_include(include)

    return ExportFilters(
        date_from=parsed_from,
        date_to=parsed_to,
        user_ids=parsed_ids,
        role=parsed_role,
        region=region if region else None,
        include=parsed_include,
    )


def _parse_date(raw: str | None, field: str) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field}: expected YYYY-MM-DD, got {raw!r}",
        )


def _parse_user_ids(raw: str | None) -> list[int] | None:
    if raw is None or raw.strip() == "":
        return None
    out: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"user_ids: non-integer token {token!r}",
            )
    return out or None


def _parse_role(raw: str | None):
    if raw is None or raw == "":
        return None
    if raw not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {sorted(_ALLOWED_ROLES)}",
        )
    return raw


def _parse_include(raw: str | None) -> frozenset[str]:
    if raw is None or raw.strip() == "":
        return INCLUDE_KINDS
    tokens = {t.strip() for t in raw.split(",") if t.strip()}
    unknown = tokens - INCLUDE_KINDS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"include: unknown token(s) {sorted(unknown)}; "
                f"allowed={sorted(INCLUDE_KINDS)}"
            ),
        )
    tokens.add("meta")  # meta는 항상 포함
    return frozenset(tokens)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_admin_export_filters.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add app/schemas/admin_export.py tests/unit/test_admin_export_filters.py
git commit -m "feat(admin-export): add ExportFilters schema + parse_filters dependency"
```

---

### Task 3: AdminExportService — Collector & CSV/README Builders

**Specialist:** backend-engineer
**Depends on:**
- Task 1 (`app/utils/admin_export_naming.py` 헬퍼)
- Task 2 (`app/schemas/admin_export.ExportFilters`)

**Produces:** `app/services/admin_export_service.py` exposing:
- `class AdminExportService(db: AsyncSession)`
- `async def collect(self, filters: ExportFilters) -> ExportPlan`
- `ExportPlan` dataclass with: `users: list[UserContext]`, `reports: list[ReportEntry]`, `sessions: list[SessionEntry]`, `lessonplans: list[LessonplanEntry]`, `filters: ExportFilters`, `generated_at: datetime`
- `build_manifest_csv(plan: ExportPlan) -> bytes`
- `build_users_csv(plan: ExportPlan) -> bytes`
- `build_readme(plan: ExportPlan) -> bytes`

각 `*Entry`는 archive path, on-disk source path(있으면), kind, user_id, resource_id 등을 담은 dataclass.

**Files:**
- Create: `app/services/admin_export_service.py`
- Create: `tests/test_admin_export_service.py`

**Step 1: Write the failing test**

```python
# tests/test_admin_export_service.py
import csv
import io
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.user_profiles import UserProfile
from app.models.users import User
from app.schemas.admin_export import ExportFilters
from app.services.admin_export_service import (
    AdminExportService,
    build_manifest_csv,
    build_readme,
    build_users_csv,
)


@pytest_asyncio_fixture := pytest.fixture  # alias for readability


@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed_user(session, *, user_id, email, role,
                     region=None, tenure=None):
    user = User(
        id=user_id,
        username=f"u{user_id}",
        nickname=f"n{user_id}",
        email=email,
    )
    session.add(user)
    await session.flush()
    if role == "teacher":
        profile = UserProfile(
            user_id=user_id,
            role=role,
            teacher_region=region,
            teacher_career_years=tenure,
        )
    else:
        profile = UserProfile(
            user_id=user_id,
            role=role,
            preservice_university_region=region,
            preservice_grade=tenure,
        )
    session.add(profile)
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_collect_filters_by_role(db_session):
    await _seed_user(
        db_session, user_id=1, email="t@x.com",
        role="teacher", region="서울", tenure=10,
    )
    await _seed_user(
        db_session, user_id=2, email="p@x.com",
        role="preservice_teacher", region="부산", tenure=3,
    )
    svc = AdminExportService(db_session)
    plan = await svc.collect(
        ExportFilters(role="teacher")
    )
    assert {u.user_id for u in plan.users} == {1}


@pytest.mark.asyncio
async def test_collect_filters_by_region(db_session):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
    await _seed_user(
        db_session, user_id=2, email="b@x.com",
        role="teacher", region="부산", tenure=5,
    )
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters(region="서울"))
    assert {u.user_id for u in plan.users} == {1}


@pytest.mark.asyncio
async def test_collect_filters_by_date_range(db_session):
    user = await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
    old = AnalysisReport(
        user_id=1,
        lessonplan_filename="1_old.pdf",
        lessonplan_original_name="old.pdf",
        report_filename="1_old_reports.md",
        report_path="/tmp/old.md",
        created_at=datetime(2026, 1, 15),
    )
    new = AnalysisReport(
        user_id=1,
        lessonplan_filename="1_new.pdf",
        lessonplan_original_name="new.pdf",
        report_filename="1_new_reports.md",
        report_path="/tmp/new.md",
        created_at=datetime(2026, 4, 15),
    )
    db_session.add_all([old, new])
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(
        ExportFilters(date_from=datetime(2026, 4, 1).date())
    )
    assert {r.resource_id for r in plan.reports} == {new.id}


@pytest.mark.asyncio
async def test_collect_filters_by_user_ids(db_session):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
    await _seed_user(
        db_session, user_id=2, email="b@x.com",
        role="teacher", region="서울", tenure=5,
    )
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters(user_ids=[2]))
    assert {u.user_id for u in plan.users} == {2}


@pytest.mark.asyncio
async def test_collect_includes_sessions_and_messages(db_session):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
    s = ChatSession(user_id=1, title="t1")
    db_session.add(s)
    await db_session.flush()
    db_session.add_all([
        ChatMessage(
            session_id=s.id, role=MessageRole.USER, content="hi"
        ),
        ChatMessage(
            session_id=s.id,
            role=MessageRole.ASSISTANT,
            content="hello",
        ),
    ])
    await db_session.commit()
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    assert len(plan.sessions) == 1
    assert plan.sessions[0].message_count == 2


@pytest.mark.asyncio
async def test_manifest_csv_shape(db_session):
    await _seed_user(
        db_session, user_id=42, email="kim@example.com",
        role="teacher", region="서울", tenure=12,
    )
    db_session.add(AnalysisReport(
        user_id=42,
        lessonplan_filename="42_lp.pdf",
        lessonplan_original_name="1학년_지도안.pdf",
        report_filename="42_lp_reports.md",
        report_path="/tmp/r.md",
        created_at=datetime(2026, 3, 1, 10, 22, 5),
    ))
    await db_session.commit()
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())

    raw = build_manifest_csv(plan)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert any(
        r["kind"] == "report"
        and r["user_id"] == "42"
        and r["user_email"] == "kim@example.com"
        and r["role"] == "teacher"
        and r["region"] == "서울"
        and r["tenure"] == "12"
        and r["tenure_kind"] == "years"
        and r["archive_path"].startswith("reports/T-서울-12y__u00042__")
        for r in rows
    )


@pytest.mark.asyncio
async def test_users_csv_counts(db_session):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
    db_session.add(AnalysisReport(
        user_id=1,
        lessonplan_filename="1_a.pdf",
        lessonplan_original_name="a.pdf",
        report_filename="1_a_reports.md",
        report_path="/tmp/a.md",
        created_at=datetime(2026, 3, 1),
    ))
    await db_session.commit()
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    raw = build_users_csv(plan)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert rows[0]["user_id"] == "1"
    assert rows[0]["n_reports"] == "1"
    assert rows[0]["n_sessions"] == "0"
    assert rows[0]["n_lessonplans"] == "1"


@pytest.mark.asyncio
async def test_readme_mentions_filters(db_session):
    svc = AdminExportService(db_session)
    plan = await svc.collect(
        ExportFilters(role="teacher", region="서울")
    )
    text = build_readme(plan).decode("utf-8")
    assert "role=teacher" in text
    assert "region=서울" in text
    assert "manifest.csv" in text
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_admin_export_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.admin_export_service'`

**Step 3: Write minimal implementation**

Create `app/services/admin_export_service.py`:

```python
"""관리자 일괄 내보내기 — 비동기 수집 + CSV/README 빌더."""
from __future__ import annotations

import csv
import hashlib
import io
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage
from app.models.chat_sessions import ChatSession
from app.models.user_profiles import UserProfile
from app.models.users import User
from app.schemas.admin_export import ExportFilters
from app.utils.admin_export_naming import (
    NormalizedProfile,
    build_filename_prefix,
    normalize_profile_fields,
    slugify_original_name,
)


LESSONPLAN_BASE_DIR = "data/lessonplan"


@dataclass(frozen=True)
class UserContext:
    user_id: int
    user_email: str | None
    role: str | None
    profile: NormalizedProfile
    filename_prefix: str
    last_login_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class ReportEntry:
    kind: str  # "report"
    user_id: int
    resource_id: int
    session_id: int | None
    created_at: datetime
    original_name: str
    archive_path: str
    source_path: str  # on-disk .md path


@dataclass(frozen=True)
class SessionEntry:
    kind: str  # "conversation"
    user_id: int
    resource_id: int  # session_id
    session_id: int
    created_at: datetime
    original_name: str  # session title or ""
    archive_path: str
    message_count: int


@dataclass(frozen=True)
class LessonplanEntry:
    kind: str  # "lessonplan"
    user_id: int
    resource_id: int  # analysis_report.id
    session_id: int | None
    created_at: datetime
    original_name: str
    archive_path: str
    source_path: str  # data/lessonplan/<filename>


@dataclass(frozen=True)
class ExportPlan:
    users: list[UserContext]
    reports: list[ReportEntry] = field(default_factory=list)
    sessions: list[SessionEntry] = field(default_factory=list)
    lessonplans: list[LessonplanEntry] = field(default_factory=list)
    session_messages: dict[int, list[ChatMessage]] = field(
        default_factory=dict
    )
    filters: ExportFilters = field(default_factory=ExportFilters)
    generated_at: datetime = field(default_factory=datetime.utcnow)


class AdminExportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def collect(self, filters: ExportFilters) -> ExportPlan:
        users = await self._collect_users(filters)
        if not users:
            return ExportPlan(users=[], filters=filters)
        user_ids = [u.user_id for u in users]
        ctx_by_id = {u.user_id: u for u in users}

        reports, lessonplans = await self._collect_reports(
            user_ids, ctx_by_id, filters
        )
        sessions, messages = await self._collect_sessions(
            user_ids, ctx_by_id, filters
        )

        return ExportPlan(
            users=users,
            reports=reports,
            sessions=sessions,
            lessonplans=lessonplans,
            session_messages=messages,
            filters=filters,
            generated_at=datetime.utcnow(),
        )

    # -------- internal --------

    async def _collect_users(
        self, filters: ExportFilters
    ) -> list[UserContext]:
        stmt = (
            select(User)
            .options(joinedload(User.profile))
            .order_by(User.id.asc())
        )
        if filters.user_ids:
            stmt = stmt.where(User.id.in_(filters.user_ids))
        if filters.role:
            stmt = stmt.where(UserProfile.role == filters.role)
            stmt = stmt.join(UserProfile)
        if filters.region:
            stmt = stmt.join(UserProfile).where(
                (UserProfile.teacher_region == filters.region)
                | (
                    UserProfile.preservice_university_region
                    == filters.region
                )
            )
        result = await self.db.execute(stmt)
        users = result.unique().scalars().all()

        out: list[UserContext] = []
        for u in users:
            profile = u.profile
            role = profile.role if profile else None
            norm = normalize_profile_fields(role, profile, u.email)
            out.append(
                UserContext(
                    user_id=u.id,
                    user_email=u.email,
                    role=role,
                    profile=norm,
                    filename_prefix=build_filename_prefix(u.id, norm),
                    last_login_at=None,
                    created_at=u.created_at,
                )
            )
        return out

    async def _collect_reports(
        self, user_ids, ctx_by_id, filters
    ) -> tuple[list[ReportEntry], list[LessonplanEntry]]:
        if "reports" not in filters.include and (
            "lessonplans" not in filters.include
        ):
            return [], []
        stmt = (
            select(AnalysisReport)
            .where(AnalysisReport.user_id.in_(user_ids))
            .order_by(AnalysisReport.created_at.asc())
        )
        if filters.date_from:
            stmt = stmt.where(
                AnalysisReport.created_at
                >= datetime.combine(
                    filters.date_from, datetime.min.time()
                )
            )
        if filters.date_to:
            stmt = stmt.where(
                AnalysisReport.created_at
                < datetime.combine(
                    filters.date_to, datetime.max.time()
                )
            )
        rows = (await self.db.execute(stmt)).scalars().all()

        reports: list[ReportEntry] = []
        lessonplans: list[LessonplanEntry] = []
        for r in rows:
            ctx = ctx_by_id[r.user_id]
            original = r.lessonplan_original_name or r.lessonplan_filename
            if "reports" in filters.include:
                fname = (
                    f"{ctx.filename_prefix}__report_{r.id}__"
                    f"{slugify_original_name(_strip_ext(original))}.md"
                )
                reports.append(
                    ReportEntry(
                        kind="report",
                        user_id=r.user_id,
                        resource_id=r.id,
                        session_id=None,
                        created_at=r.created_at,
                        original_name=original,
                        archive_path=f"reports/{fname}",
                        source_path=r.report_path,
                    )
                )
            if "lessonplans" in filters.include:
                lp_name = (
                    f"{ctx.filename_prefix}__lessonplan_{r.id}__"
                    f"{slugify_original_name(original)}"
                )
                lp_path = os.path.join(
                    LESSONPLAN_BASE_DIR, r.lessonplan_filename
                )
                lessonplans.append(
                    LessonplanEntry(
                        kind="lessonplan",
                        user_id=r.user_id,
                        resource_id=r.id,
                        session_id=None,
                        created_at=r.created_at,
                        original_name=original,
                        archive_path=f"lessonplans/{lp_name}",
                        source_path=lp_path,
                    )
                )
        return reports, lessonplans

    async def _collect_sessions(
        self, user_ids, ctx_by_id, filters
    ) -> tuple[list[SessionEntry], dict[int, list[ChatMessage]]]:
        if "conversations" not in filters.include:
            return [], {}
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id.in_(user_ids))
            .options(selectinload(ChatSession.messages))
            .order_by(ChatSession.created_at.asc())
        )
        if filters.date_from:
            stmt = stmt.where(
                ChatSession.created_at
                >= datetime.combine(
                    filters.date_from, datetime.min.time()
                )
            )
        if filters.date_to:
            stmt = stmt.where(
                ChatSession.created_at
                < datetime.combine(
                    filters.date_to, datetime.max.time()
                )
            )
        rows = (await self.db.execute(stmt)).scalars().all()

        sessions: list[SessionEntry] = []
        msgs: dict[int, list[ChatMessage]] = {}
        for s in rows:
            ctx = ctx_by_id[s.user_id]
            fname = (
                f"{ctx.filename_prefix}__session_{s.id}.jsonl"
            )
            sorted_msgs = sorted(
                s.messages, key=lambda m: m.created_at
            )
            sessions.append(
                SessionEntry(
                    kind="conversation",
                    user_id=s.user_id,
                    resource_id=s.id,
                    session_id=s.id,
                    created_at=s.created_at,
                    original_name=s.title or "",
                    archive_path=f"conversations/{fname}",
                    message_count=len(sorted_msgs),
                )
            )
            msgs[s.id] = sorted_msgs
        return sessions, msgs


def _strip_ext(name: str) -> str:
    return os.path.splitext(name)[0] if name else name


# -------- CSV / README builders --------


_MANIFEST_COLUMNS = [
    "kind",
    "user_id",
    "user_email",
    "role",
    "region",
    "tenure",
    "tenure_kind",
    "resource_id",
    "session_id",
    "created_at",
    "original_name",
    "archive_path",
    "byte_size",
    "sha256",
]

_USERS_COLUMNS = [
    "user_id",
    "user_email",
    "role",
    "region",
    "tenure",
    "tenure_kind",
    "created_at",
    "last_login_at",
    "n_reports",
    "n_sessions",
    "n_lessonplans",
]


def build_manifest_csv(plan: ExportPlan) -> bytes:
    """sha256/byte_size는 ZIP 단계에서 채워지므로 빈 칸으로 둔다."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_MANIFEST_COLUMNS)
    w.writeheader()
    ctx_by_id = {u.user_id: u for u in plan.users}
    iter_entries: Iterable = (
        list(plan.reports) + list(plan.sessions) + list(plan.lessonplans)
    )
    for e in iter_entries:
        ctx = ctx_by_id[e.user_id]
        w.writerow({
            "kind": e.kind,
            "user_id": e.user_id,
            "user_email": ctx.user_email or "",
            "role": ctx.role or "",
            "region": ctx.profile.region_slug,
            "tenure": ctx.profile.tenure,
            "tenure_kind": ctx.profile.tenure_kind,
            "resource_id": e.resource_id,
            "session_id": e.session_id or "",
            "created_at": (
                e.created_at.isoformat() if e.created_at else ""
            ),
            "original_name": e.original_name,
            "archive_path": e.archive_path,
            "byte_size": "",
            "sha256": "",
        })
    return buf.getvalue().encode("utf-8")


def build_users_csv(plan: ExportPlan) -> bytes:
    counts: dict[int, dict[str, int]] = {
        u.user_id: {"r": 0, "s": 0, "l": 0} for u in plan.users
    }
    for r in plan.reports:
        counts[r.user_id]["r"] += 1
    for s in plan.sessions:
        counts[s.user_id]["s"] += 1
    for l in plan.lessonplans:
        counts[l.user_id]["l"] += 1

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_USERS_COLUMNS)
    w.writeheader()
    for u in plan.users:
        w.writerow({
            "user_id": u.user_id,
            "user_email": u.user_email or "",
            "role": u.role or "",
            "region": u.profile.region_slug,
            "tenure": u.profile.tenure,
            "tenure_kind": u.profile.tenure_kind,
            "created_at": (
                u.created_at.isoformat() if u.created_at else ""
            ),
            "last_login_at": (
                u.last_login_at.isoformat()
                if u.last_login_at else ""
            ),
            "n_reports": counts[u.user_id]["r"],
            "n_sessions": counts[u.user_id]["s"],
            "n_lessonplans": counts[u.user_id]["l"],
        })
    return buf.getvalue().encode("utf-8")


def build_readme(plan: ExportPlan) -> bytes:
    lines = [
        "ELP Bulk Export",
        f"Generated at: {plan.generated_at.isoformat()}Z",
        "",
        "Filters:",
        f"  date_from={plan.filters.date_from}",
        f"  date_to={plan.filters.date_to}",
        f"  user_ids={plan.filters.user_ids}",
        f"  role={plan.filters.role}",
        f"  region={plan.filters.region}",
        f"  include={sorted(plan.filters.include)}",
        "",
        f"Counts:",
        f"  users={len(plan.users)}",
        f"  reports={len(plan.reports)}",
        f"  conversations={len(plan.sessions)}",
        f"  lessonplans={len(plan.lessonplans)}",
        "",
        "Layout:",
        "  manifest.csv      마스터 인덱스 (자원→파일 매핑)",
        "  users.csv         사용자 메타데이터 + 자원 개수",
        "  reports/          분석 보고서 (.md)",
        "  conversations/    QnA 세션 대화 (.jsonl)",
        "  lessonplans/      원본 수업 지도안",
        "",
        "파일명 규칙:",
        "  {role-region-tenure}__u{user_id}__{email_slug}__"
        "{resource_kind}_{resource_id}__{original_name}.{ext}",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_admin_export_service.py -v`
Expected: PASS (8 tests)

Note: 테스트 픽스처 `pytest_asyncio_fixture := pytest.fixture` 한 줄은 가독성용 alias. `pytest-asyncio`가 이미 conftest에 설치돼 있으므로 `@pytest.fixture` + `async def`로 동작한다. 동작 안 하면 `@pytest_asyncio.fixture`로 교체.

**Step 5: Commit**

```bash
git add app/services/admin_export_service.py tests/test_admin_export_service.py
git commit -m "feat(admin-export): add async collector + CSV/README builders"
```

---

### Task 4: Admin UI — Export Button & Link

**Specialist:** frontend-engineer
**Depends on:** None (URL/parameter 스펙은 본 plan의 Task 5 명세를 그대로 따른다)
**Produces:** 관리자 대시보드 페이지 상단에 "전체 데이터 내보내기" 버튼 + 모달, 사용자 상세 페이지에 "이 사용자만 내보내기" 링크.

**Files:**
- Modify: `app/templates/admin/admin_dashboard.html` (버튼 + 모달 + 인라인 JS 추가)
- Modify: `app/templates/admin/admin_user_detail.html` (헤더에 링크 1개 추가)

**Step 1: Inspect current dashboard to find insertion point**

Run: `grep -n "보고서\|users-stats\|<main\|<header\|<body" /home/dominemint/Dev/elp_gemini/app/templates/admin/admin_dashboard.html | head -20`
Expected: 페이지 헤더 또는 통계 카드 직후 위치를 식별.

**Step 2: Add export button + modal markup to dashboard**

`admin_dashboard.html` — 페이지 상단 헤더 영역 (h1 또는 첫 섹션 카드) 바로 아래에 다음 블록 추가:

```html
<!-- 전체 데이터 내보내기 -->
<div class="mb-6">
  <button id="openExportModalBtn"
          type="button"
          class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
    전체 데이터 내보내기 (ZIP)
  </button>
</div>

<div id="exportModal"
     class="hidden fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
  <div class="bg-white rounded-lg shadow-lg p-6 w-full max-w-md">
    <h3 class="text-lg font-bold mb-4">데이터 일괄 내보내기</h3>

    <form id="exportForm" class="space-y-4">
      <div>
        <label class="block text-sm font-medium">기간 (선택)</label>
        <div class="flex gap-2">
          <input type="date" name="date_from"
                 class="border rounded px-2 py-1 w-full" />
          <input type="date" name="date_to"
                 class="border rounded px-2 py-1 w-full" />
        </div>
      </div>

      <div>
        <label class="block text-sm font-medium">신분 (선택)</label>
        <select name="role" class="border rounded px-2 py-1 w-full">
          <option value="">전체</option>
          <option value="teacher">현직교사</option>
          <option value="preservice_teacher">예비교원</option>
        </select>
      </div>

      <div>
        <label class="block text-sm font-medium">지역 (선택)</label>
        <input type="text" name="region" placeholder="예: 서울"
               class="border rounded px-2 py-1 w-full" />
      </div>

      <div>
        <label class="block text-sm font-medium">포함 데이터</label>
        <div class="flex flex-wrap gap-3 text-sm">
          <label><input type="checkbox" name="include" value="reports"
                        checked /> 보고서</label>
          <label><input type="checkbox" name="include" value="conversations"
                        checked /> 대화</label>
          <label><input type="checkbox" name="include" value="lessonplans"
                        checked /> 원본 지도안</label>
        </div>
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <button type="button" id="cancelExportBtn"
                class="px-3 py-1 border rounded">취소</button>
        <button type="submit"
                class="px-3 py-1 bg-blue-600 text-white rounded">
          다운로드
        </button>
      </div>
    </form>
  </div>
</div>

<script>
(() => {
  const modal = document.getElementById("exportModal");
  const openBtn = document.getElementById("openExportModalBtn");
  const cancelBtn = document.getElementById("cancelExportBtn");
  const form = document.getElementById("exportForm");

  openBtn.addEventListener("click", () => modal.classList.remove("hidden"));
  cancelBtn.addEventListener("click", () => modal.classList.add("hidden"));

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const params = new URLSearchParams();
    const dateFrom = fd.get("date_from");
    const dateTo = fd.get("date_to");
    const role = fd.get("role");
    const region = (fd.get("region") || "").trim();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (role) params.set("role", role);
    if (region) params.set("region", region);
    const include = fd.getAll("include");
    if (include.length) params.set("include", include.join(","));
    window.location.href =
      "/admin/api/exports/all.zip?" + params.toString();
    modal.classList.add("hidden");
  });
})();
</script>
```

**Step 3: Add per-user export link to user detail**

`admin_user_detail.html` — 페이지 헤더 영역 (사용자 정보 카드 근처)에 다음 추가:

```html
<a id="exportUserLink"
   href="#"
   class="inline-block px-3 py-1 border rounded text-sm hover:bg-gray-50">
  이 사용자만 ZIP으로 내보내기
</a>
<script>
  (() => {
    const userId = document.body.dataset.userId
      || new URL(window.location.href).pathname.split("/").pop();
    const link = document.getElementById("exportUserLink");
    link.href = "/admin/api/exports/all.zip?user_ids=" + userId;
  })();
</script>
```

(`data-user-id` 속성이 body나 main 요소에 이미 있으면 그걸 사용. 없으면 URL의 마지막 path segment를 폴백.)

**Step 4: Verify UI renders without server-side errors**

Run app locally — `.venv/bin/python -m uvicorn app.main:app --reload --port 8000`
브라우저로 `/admin` 접속 → 버튼 보임 + 클릭 시 모달 열림 + 다운로드 클릭 시 `/admin/api/exports/all.zip?...` 로 GET (현재는 404가 정상; Task 5 이후 정상 작동).

**Step 5: Commit**

```bash
git add app/templates/admin/admin_dashboard.html app/templates/admin/admin_user_detail.html
git commit -m "feat(admin-export): add export modal on dashboard + per-user link"
```

---

### Task 5: ZIP Streamer & Router Endpoint

**Specialist:** backend-engineer
**Depends on:**
- Task 1 (slug helpers — 이미 `admin_export_service.py`가 사용 중)
- Task 2 (`ExportFilters`, `parse_filters`)
- Task 3 (`AdminExportService.collect`, CSV/README builders)

**Produces:** `app/routers/admin/exports.py` 라우터 + `app/main.py`에 등록 + `app/services/admin_export_service.py`에 `stream_zip(plan)` 메서드 추가.

**Files:**
- Modify: `app/services/admin_export_service.py` (add `stream_zip` 메서드 + `_ChunkBuffer` + `_iter_entries`)
- Create: `app/routers/admin/exports.py`
- Modify: `app/main.py` (라우터 등록 1줄)
- Create: `tests/test_admin_exports_endpoint.py`

**Step 1: Write the failing test (endpoint + ZIP integrity)**

```python
# tests/test_admin_exports_endpoint.py
import io
import json
import os
import zipfile

import pytest
from httpx import AsyncClient

from app.main import app
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.user_profiles import UserProfile
from app.models.users import User


@pytest.mark.asyncio
async def test_export_requires_admin(client_unauth):
    resp = await client_unauth.get("/admin/api/exports/all.zip")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_export_returns_valid_zip(client_admin, db_session, tmp_path):
    # 사용자/프로필/보고서/세션을 seed
    user = User(
        id=42, username="u42", nickname="kim",
        email="kim@example.com",
    )
    db_session.add(user)
    db_session.add(UserProfile(
        user_id=42, role="teacher",
        teacher_region="서울",
        teacher_career_years=12,
    ))
    report_md = tmp_path / "report.md"
    report_md.write_text("# Report\nHello", encoding="utf-8")
    db_session.add(AnalysisReport(
        user_id=42,
        lessonplan_filename="42_lp.pdf",
        lessonplan_original_name="1학년_지도안.pdf",
        report_filename="42_lp_reports.md",
        report_path=str(report_md),
    ))
    s = ChatSession(user_id=42, title="t1")
    db_session.add(s)
    await db_session.flush()
    db_session.add_all([
        ChatMessage(
            session_id=s.id, role=MessageRole.USER, content="안녕"
        ),
        ChatMessage(
            session_id=s.id,
            role=MessageRole.ASSISTANT,
            content="hello",
        ),
    ])
    await db_session.commit()

    resp = await client_admin.get("/admin/api/exports/all.zip")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert "manifest.csv" in names
    assert "users.csv" in names
    assert "README.txt" in names
    assert any(n.startswith("reports/T-서울-12y__u00042__") for n in names)
    assert any(n.startswith("conversations/T-서울-12y__u00042__") for n in names)
    convo = [n for n in names if n.startswith("conversations/")][0]
    lines = zf.read(convo).decode("utf-8").splitlines()
    parsed = [json.loads(l) for l in lines]
    assert len(parsed) == 2
    assert parsed[0]["role"] == "user"


@pytest.mark.asyncio
async def test_export_filter_role(client_admin, db_session):
    db_session.add(User(
        id=1, username="t", nickname="t", email="t@x.com"
    ))
    db_session.add(UserProfile(
        user_id=1, role="teacher",
        teacher_region="서울", teacher_career_years=5,
    ))
    db_session.add(User(
        id=2, username="p", nickname="p", email="p@x.com"
    ))
    db_session.add(UserProfile(
        user_id=2, role="preservice_teacher",
        preservice_university_region="부산",
        preservice_grade=3,
    ))
    await db_session.commit()

    resp = await client_admin.get(
        "/admin/api/exports/all.zip?role=teacher"
    )
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    users_csv = zf.read("users.csv").decode("utf-8")
    assert "1,t@x.com,teacher" in users_csv
    assert "2,p@x.com" not in users_csv


@pytest.mark.asyncio
async def test_export_invalid_date_returns_400(client_admin):
    resp = await client_admin.get(
        "/admin/api/exports/all.zip?date_from=2026-99-01"
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_export_missing_lessonplan_marks_in_manifest(
    client_admin, db_session
):
    db_session.add(User(
        id=1, username="t", nickname="t", email="t@x.com"
    ))
    db_session.add(UserProfile(
        user_id=1, role="teacher",
        teacher_region="서울", teacher_career_years=5,
    ))
    db_session.add(AnalysisReport(
        user_id=1,
        lessonplan_filename="does_not_exist.pdf",
        lessonplan_original_name="missing.pdf",
        report_filename="x.md",
        report_path="/no/such/path.md",
    ))
    await db_session.commit()

    resp = await client_admin.get("/admin/api/exports/all.zip")
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    manifest = zf.read("manifest.csv").decode("utf-8")
    assert "MISSING" in manifest
```

Fixture `client_admin`, `client_unauth`, `db_session`은 `tests/conftest.py`에 추가/확장 필요. 기존 `tests/test_admin_user_detail_parity.py` 등을 참고해 admin 로그인 세션을 부여한 `AsyncClient`를 만들 것.

**Step 2: Run tests — expect failures**

Run: `.venv/bin/python -m pytest tests/test_admin_exports_endpoint.py -v`
Expected: FAIL with 404 (라우터 미등록) 또는 fixture 미존재.

**Step 3: Add `stream_zip` to AdminExportService**

`app/services/admin_export_service.py`에 추가:

```python
import zipfile
from typing import Iterator


class _ChunkBuffer:
    def __init__(self):
        self._buf = bytearray()

    def write(self, data):
        self._buf.extend(data)
        return len(data)

    def flush(self):
        pass

    def take(self) -> bytes:
        chunk = bytes(self._buf)
        self._buf.clear()
        return chunk


# AdminExportService 클래스에 메서드 추가:

    def stream_zip(self, plan: ExportPlan) -> Iterator[bytes]:
        buf = _ChunkBuffer()
        with zipfile.ZipFile(
            buf, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            yield from self._emit_meta(zf, buf, plan)
            yield from self._emit_reports(zf, buf, plan)
            yield from self._emit_conversations(zf, buf, plan)
            yield from self._emit_lessonplans(zf, buf, plan)
        yield buf.take()

    def _emit_meta(self, zf, buf, plan):
        if "meta" in plan.filters.include:
            zf.writestr("README.txt", build_readme(plan))
            yield buf.take()
            zf.writestr("manifest.csv", build_manifest_csv(plan))
            yield buf.take()
            zf.writestr("users.csv", build_users_csv(plan))
            yield buf.take()

    def _emit_reports(self, zf, buf, plan):
        if "reports" not in plan.filters.include:
            return
        for r in plan.reports:
            data, sha = _read_file_or_missing(r.source_path)
            zf.writestr(r.archive_path, data)
            yield buf.take()

    def _emit_conversations(self, zf, buf, plan):
        if "conversations" not in plan.filters.include:
            return
        for s in plan.sessions:
            payload = _serialize_session_jsonl(
                s, plan.session_messages.get(s.session_id, [])
            )
            zf.writestr(s.archive_path, payload)
            yield buf.take()

    def _emit_lessonplans(self, zf, buf, plan):
        if "lessonplans" not in plan.filters.include:
            return
        for l in plan.lessonplans:
            data, sha = _read_file_or_missing(l.source_path)
            zf.writestr(l.archive_path, data)
            yield buf.take()


def _read_file_or_missing(path: str) -> tuple[bytes, str]:
    try:
        with open(path, "rb") as f:
            data = f.read()
        return data, hashlib.sha256(data).hexdigest()
    except FileNotFoundError:
        return b"", "MISSING"


def _serialize_session_jsonl(
    session_entry, messages
) -> bytes:
    import json
    lines = []
    for m in messages:
        lines.append(json.dumps({
            "session_id": session_entry.session_id,
            "message_id": m.id,
            "role": m.role.value if hasattr(m.role, "value")
                    else str(m.role),
            "content": m.content,
            "created_at": (
                m.created_at.isoformat() if m.created_at else None
            ),
        }, ensure_ascii=False))
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
```

또한 `build_manifest_csv`가 `byte_size`/`sha256`을 실제로 채우도록 stream pass 후 다시 쓰는 건 복잡하므로 — 본 설계는 단일 스트림이라 사후 갱신이 어렵다. 결정:
- **manifest.csv는 `byte_size`/`sha256`을 채우지 않고 비워둔다.** 위 테스트가 그 두 컬럼 값을 검증하지 않도록 작성됨.
- `_read_file_or_missing`이 반환하는 `sha`는 누락 표시("MISSING")만 manifest에 반영하기 위해 사용 — manifest는 ZIP 직전에 한 번 더 빌드하고, missing 표시는 별도 set로 collect 단계에서 미리 가려둘 수 있다. 단순화를 위해 **manifest는 archive_path만 정확하면 충분**하다는 입장을 채택. `byte_size`/`sha256` 채우려면 두 패스 빌드가 필요하므로 현재 범위에서는 빈 칸으로 두고, 추후 별도 task로 분리.

→ 누락 파일 표시는 manifest에서 별도 컬럼 `source_status`(`OK`/`MISSING`)로 대체. `_collect_reports`/`_collect_lessonplans`에서 미리 파일 존재 여부를 확인하고 `ReportEntry`/`LessonplanEntry`에 `source_status` 필드 추가. `build_manifest_csv`가 그 값을 새 컬럼으로 출력. 테스트는 `"MISSING" in manifest`만 검사하므로 호환됨.

`_MANIFEST_COLUMNS`에 `source_status` 추가하고, ReportEntry/LessonplanEntry에 `source_status: str = "OK"` 필드 추가. `_collect_reports`/`_collect_lessonplans`에서 `os.path.exists(...)`로 결정.

**Step 4: Create router**

```python
# app/routers/admin/exports.py
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.schemas.admin_export import ExportFilters, parse_filters
from app.services.admin_export_service import AdminExportService


router = APIRouter(tags=["admin-exports"])


@router.get("/admin/api/exports/all.zip")
async def export_all(
    filters: ExportFilters = Depends(parse_filters),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    service = AdminExportService(db)
    plan = await service.collect(filters)
    filename = (
        f"elp_export_{datetime.utcnow():%Y%m%d_%H%M%S}.zip"
    )
    return StreamingResponse(
        service.stream_zip(plan),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            ),
        },
    )
```

**Step 5: Register router in main.py**

`app/main.py`에 다음 1줄 추가 (다른 admin 라우터들 옆):

```python
from app.routers.admin import exports as admin_exports

# ... 기존 include_router 호출들 옆에
app.include_router(admin_exports.router)
```

**Step 6: Run all new tests to verify**

Run:
```bash
.venv/bin/python -m pytest \
    tests/unit/test_admin_export_naming.py \
    tests/unit/test_admin_export_filters.py \
    tests/test_admin_export_service.py \
    tests/test_admin_exports_endpoint.py -v
```
Expected: ALL PASS

**Step 7: Run full test suite for regression**

Run: `.venv/bin/python -m pytest -q`
Expected: 기존 테스트 그대로 PASS + 신규 PASS

**Step 8: Smoke test manually**

Run: `.venv/bin/python -m uvicorn app.main:app --reload --port 8000`

브라우저로 admin 로그인 후 `/admin/api/exports/all.zip` 호출 → ZIP 다운로드 → `unzip -l` 로 구조 확인:
```bash
unzip -l ~/Downloads/elp_export_*.zip
```
Expected: `manifest.csv`, `users.csv`, `README.txt`, `reports/...`, `conversations/...`, `lessonplans/...`.

**Step 9: Commit**

```bash
git add \
  app/services/admin_export_service.py \
  app/routers/admin/exports.py \
  app/main.py \
  tests/test_admin_exports_endpoint.py
git commit -m "feat(admin-export): add /admin/api/exports/all.zip endpoint with ZIP streaming"
```

---

## Execution

Plan complete and saved to `docs/plans/2026-05-11-admin-bulk-export.md`.

**Recommended: Agent Team-Driven** — Parallel specialist agents, wave-based execution, two-stage review after each task.

**Alternative: Subagent-Driven** — Serial execution, simpler orchestration, no team overhead. Better if <3 tasks or tasks are tightly coupled.

Which approach?
