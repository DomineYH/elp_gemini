"""관리자 일괄 내보내기 — 비동기 수집 + CSV/README 빌더."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Iterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, joinedload, selectinload

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
    source_status: str = "OK"


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
    source_status: str = "OK"


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
        needs_join = bool(filters.role) or bool(filters.region)
        stmt = select(User).order_by(User.id.asc())
        if filters.user_ids:
            stmt = stmt.where(User.id.in_(filters.user_ids))
        if needs_join:
            stmt = stmt.join(User.profile).options(
                contains_eager(User.profile)
            )
            if filters.role:
                stmt = stmt.where(UserProfile.role == filters.role)
            if filters.region:
                stmt = stmt.where(
                    (UserProfile.teacher_region == filters.region)
                    | (
                        UserProfile.preservice_university_region
                        == filters.region
                    )
                )
        else:
            stmt = stmt.options(joinedload(User.profile))
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
                    filters.date_to, datetime.min.time()
                ) + timedelta(days=1)
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
                report_status = (
                    "OK" if os.path.exists(r.report_path) else "MISSING"
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
                        source_status=report_status,
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
                lp_status = (
                    "OK" if os.path.exists(lp_path) else "MISSING"
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
                        source_status=lp_status,
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
                    filters.date_to, datetime.min.time()
                ) + timedelta(days=1)
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

    # -------- ZIP streaming --------

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
            data, _ = _read_file_or_missing(r.source_path)
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
            data, _ = _read_file_or_missing(l.source_path)
            zf.writestr(l.archive_path, data)
            yield buf.take()


def _strip_ext(name: str) -> str:
    return os.path.splitext(name)[0] if name else name


# -------- ZIP streaming --------


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
    "source_status",
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
            "source_status": getattr(e, "source_status", "OK"),
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
