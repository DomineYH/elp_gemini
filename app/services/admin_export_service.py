"""관리자 일괄 내보내기 — 비동기 수집 + CSV/README 빌더."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage
from app.models.chat_sessions import ChatSession
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_persona import SimulationPersona
from app.models.simulation_session import SimulationSession
from app.models.simulation_utterance import SimulationUtterance
from app.models.users import User
from app.schemas.admin_export import ExportFilters
from app.utils.admin_export_naming import (
    build_filename_prefix,
    slugify_original_name,
)
from app.utils.timestamps import kst_date_start_utc_naive

LESSONPLAN_BASE_DIR = "data/lessonplan"
STATIC_UPLOADS_DIR = "app/static/uploads"


@dataclass(frozen=True)
class UserContext:
    user_id: int
    filename_prefix: str
    username: str | None = None
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
    source_path: str  # on-disk lessonplan path
    source_status: str = "OK"


@dataclass(frozen=True)
class SimulationEntry:
    kind: str  # "simulation"
    user_id: int
    resource_id: int  # simulation session id
    session_id: int
    created_at: datetime
    archive_path: str
    persona_names: dict[int, str]  # persona_id -> display_name


@dataclass(frozen=True)
class ExportPlan:
    users: list[UserContext]
    reports: list[ReportEntry] = field(default_factory=list)
    sessions: list[SessionEntry] = field(default_factory=list)
    lessonplans: list[LessonplanEntry] = field(default_factory=list)
    session_messages: dict[int, list[ChatMessage]] = field(default_factory=dict)
    simulations: list[SimulationEntry] = field(default_factory=list)
    simulation_utterances: dict[int, list[SimulationUtterance]] = field(
        default_factory=dict
    )
    filters: ExportFilters = field(default_factory=ExportFilters)
    generated_at: datetime = field(default_factory=datetime.utcnow)


class AdminExportService:
    def __init__(
        self,
        db: AsyncSession,
        lessonplan_base_dir: str = LESSONPLAN_BASE_DIR,
        static_uploads_dir: str = STATIC_UPLOADS_DIR,
    ):
        self.db = db
        self._lessonplan_base_dir = lessonplan_base_dir
        self._static_uploads_dir = static_uploads_dir

    async def collect(self, filters: ExportFilters) -> ExportPlan:
        users = await self._collect_users(filters)
        if not users:
            return ExportPlan(users=[], filters=filters)
        user_ids = [u.user_id for u in users]
        ctx_by_id = {u.user_id: u for u in users}

        reports = await self._collect_reports(user_ids, ctx_by_id, filters)
        sessions, messages = await self._collect_sessions(
            user_ids, ctx_by_id, filters
        )
        lessonplans = await self._collect_lessonplans(users, filters)
        simulations, sim_utterances = await self._collect_simulations(
            user_ids, ctx_by_id, filters
        )

        return ExportPlan(
            users=users,
            reports=reports,
            sessions=sessions,
            lessonplans=lessonplans,
            session_messages=messages,
            simulations=simulations,
            simulation_utterances=sim_utterances,
            filters=filters,
            generated_at=datetime.utcnow(),
        )

    # -------- internal --------

    async def _collect_users(self, filters: ExportFilters) -> list[UserContext]:
        stmt = (
            select(User).where(User.is_admin.is_(False)).order_by(User.id.asc())
        )
        if filters.user_ids:
            stmt = stmt.where(User.id.in_(filters.user_ids))
        result = await self.db.execute(stmt)
        users = result.unique().scalars().all()

        out: list[UserContext] = []
        for u in users:
            out.append(
                UserContext(
                    user_id=u.id,
                    filename_prefix=build_filename_prefix(user_id=u.id),
                    username=u.username,
                    last_login_at=None,
                    created_at=u.created_at,
                )
            )
        return out

    async def _collect_reports(
        self, user_ids, ctx_by_id, filters
    ) -> list[ReportEntry]:
        if "reports" not in filters.include:
            return []
        stmt = (
            select(AnalysisReport)
            .where(AnalysisReport.user_id.in_(user_ids))
            .order_by(AnalysisReport.created_at.asc())
        )
        lower_bound, upper_bound = _date_bounds(filters)
        if lower_bound:
            stmt = stmt.where(AnalysisReport.created_at >= lower_bound)
        if upper_bound:
            stmt = stmt.where(AnalysisReport.created_at < upper_bound)
        rows = (await self.db.execute(stmt)).scalars().all()

        reports: list[ReportEntry] = []
        for r in rows:
            ctx = ctx_by_id[r.user_id]
            original = r.lessonplan_original_name or r.lessonplan_filename
            fname = (
                f"{ctx.filename_prefix}__report_{r.id}__"
                f"{slugify_original_name(_strip_ext(original))}.md"
            )
            report_status = "OK" if os.path.exists(r.report_path) else "MISSING"
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
        return reports

    async def _collect_lessonplans(
        self, users, filters
    ) -> list[LessonplanEntry]:
        """원본 지도안 파일을 파일시스템에서 열거하고 보고서 참조도 보강.

        스토리지 컨벤션:
        - per-user: data/lessonplan/{user_id}/{original_filename}
        - dashboard: app/static/uploads/{user_id}/{saved_filename}
        """
        if "lessonplans" not in filters.include:
            return []

        base = Path(self._lessonplan_base_dir)
        entries: list[LessonplanEntry] = []
        seen: set[tuple[int, str]] = set()
        ctx_by_id = {ctx.user_id: ctx for ctx in users}
        user_ids = [ctx.user_id for ctx in users]
        lower_bound, upper_bound = _date_bounds(filters)

        if base.exists():
            for ctx in users:
                user_dir = base / str(ctx.user_id)
                if not user_dir.is_dir():
                    continue
                files = sorted(user_dir.glob("*"))
                for ordinal, fpath in enumerate(files, start=1):
                    if not fpath.is_file():
                        continue
                    try:
                        stat = fpath.stat()
                    except OSError:
                        continue
                    # DB created_at과 같은 naive UTC로 맞춘다 (#211)
                    mtime = datetime.fromtimestamp(
                        stat.st_mtime, timezone.utc
                    ).replace(tzinfo=None)
                    if lower_bound and mtime < lower_bound:
                        continue
                    if upper_bound and mtime >= upper_bound:
                        continue
                    original = fpath.name
                    archive_name = (
                        f"{ctx.filename_prefix}__lessonplan_{ordinal}__"
                        f"{slugify_original_name(original)}"
                    )
                    seen.add((ctx.user_id, fpath.name))
                    entries.append(
                        LessonplanEntry(
                            kind="lessonplan",
                            user_id=ctx.user_id,
                            resource_id=ordinal,
                            session_id=None,
                            created_at=mtime,
                            original_name=original,
                            archive_path=f"lessonplans/{archive_name}",
                            source_path=str(fpath),
                            source_status="OK",
                        )
                    )

        stmt = (
            select(AnalysisReport)
            .where(AnalysisReport.user_id.in_(user_ids))
            .order_by(AnalysisReport.created_at.asc())
        )
        if lower_bound:
            stmt = stmt.where(AnalysisReport.created_at >= lower_bound)
        if upper_bound:
            stmt = stmt.where(AnalysisReport.created_at < upper_bound)
        rows = (await self.db.execute(stmt)).scalars().all()

        for r in rows:
            key = (r.user_id, r.lessonplan_filename)
            if key in seen:
                continue
            ctx = ctx_by_id[r.user_id]
            original = r.lessonplan_original_name or r.lessonplan_filename
            source_path = self._resolve_lessonplan_source_path(
                r.lessonplan_filename,
                user_id=r.user_id,
                upload_id=r.upload_id,
            )
            archive_name = (
                f"{ctx.filename_prefix}__lessonplan_{r.id}__"
                f"{slugify_original_name(original)}"
            )
            entries.append(
                LessonplanEntry(
                    kind="lessonplan",
                    user_id=r.user_id,
                    resource_id=r.id,
                    session_id=None,
                    created_at=r.created_at,
                    original_name=original,
                    archive_path=f"lessonplans/{archive_name}",
                    source_path=str(source_path),
                    source_status=(
                        "OK" if source_path.is_file() else "MISSING"
                    ),
                )
            )
            seen.add(key)

        upload_stmt = (
            select(LessonPlanUpload)
            .where(LessonPlanUpload.user_id.in_(user_ids))
            .order_by(LessonPlanUpload.created_at.asc())
        )
        if lower_bound:
            upload_stmt = upload_stmt.where(
                LessonPlanUpload.created_at >= lower_bound
            )
        if upper_bound:
            upload_stmt = upload_stmt.where(
                LessonPlanUpload.created_at < upper_bound
            )
        uploads = (await self.db.execute(upload_stmt)).scalars().all()

        for upload in uploads:
            key = (upload.user_id, upload.filename)
            if key in seen:
                continue
            ctx = ctx_by_id[upload.user_id]
            original = upload.original_filename or upload.filename
            source_path = self._resolve_lessonplan_source_path(
                upload.filename,
                user_id=upload.user_id,
                upload_id=upload.id,
            )
            archive_name = (
                f"{ctx.filename_prefix}__lessonplan_{upload.id}__"
                f"{slugify_original_name(original)}"
            )
            entries.append(
                LessonplanEntry(
                    kind="lessonplan",
                    user_id=upload.user_id,
                    resource_id=upload.id,
                    session_id=None,
                    created_at=upload.created_at,
                    original_name=original,
                    archive_path=f"lessonplans/{archive_name}",
                    source_path=str(source_path),
                    source_status=(
                        "OK" if source_path.is_file() else "MISSING"
                    ),
                )
            )
            seen.add(key)
        return entries

    def _resolve_lessonplan_source_path(
        self,
        filename: str,
        user_id: int,
        upload_id: int | None,
    ) -> Path:
        safe_name = Path(filename).name
        candidates = [
            Path(self._static_uploads_dir) / str(user_id) / safe_name,
            Path(self._lessonplan_base_dir) / str(user_id) / safe_name,
            Path(self._static_uploads_dir) / safe_name,
            Path(self._lessonplan_base_dir) / safe_name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return candidates[0]

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
        lower_bound, upper_bound = _date_bounds(filters)
        if lower_bound:
            stmt = stmt.where(ChatSession.created_at >= lower_bound)
        if upper_bound:
            stmt = stmt.where(ChatSession.created_at < upper_bound)
        rows = (await self.db.execute(stmt)).scalars().all()

        sessions: list[SessionEntry] = []
        msgs: dict[int, list[ChatMessage]] = {}
        for s in rows:
            ctx = ctx_by_id[s.user_id]
            fname = f"{ctx.filename_prefix}__session_{s.id}.jsonl"
            sorted_msgs = sorted(s.messages, key=lambda m: (m.created_at, m.id))
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

    async def _collect_simulations(
        self, user_ids, ctx_by_id, filters
    ) -> tuple[list[SimulationEntry], dict[int, list[SimulationUtterance]]]:
        # 시뮬레이션 발화는 별도 include 키 없이 conversations에 묶는다
        if "conversations" not in filters.include:
            return [], {}
        stmt = (
            select(SimulationSession)
            .where(SimulationSession.user_id.in_(user_ids))
            .order_by(SimulationSession.created_at.asc())
        )
        lower_bound, upper_bound = _date_bounds(filters)
        if lower_bound:
            stmt = stmt.where(SimulationSession.created_at >= lower_bound)
        if upper_bound:
            stmt = stmt.where(SimulationSession.created_at < upper_bound)
        rows = (await self.db.execute(stmt)).scalars().all()

        entries: list[SimulationEntry] = []
        utterances: dict[int, list[SimulationUtterance]] = {}
        for s in rows:
            ctx = ctx_by_id[s.user_id]
            personas = await self.db.scalars(
                select(SimulationPersona).where(
                    SimulationPersona.session_id == s.id
                )
            )
            entries.append(
                SimulationEntry(
                    kind="simulation",
                    user_id=s.user_id,
                    resource_id=s.id,
                    session_id=s.id,
                    created_at=s.created_at,
                    archive_path=(
                        f"simulations/{ctx.filename_prefix}"
                        f"__simsession_{s.id}.jsonl"
                    ),
                    persona_names={p.id: p.display_name for p in personas},
                )
            )
            utterances[s.id] = list(
                await self.db.scalars(
                    select(SimulationUtterance)
                    .where(SimulationUtterance.session_id == s.id)
                    .order_by(SimulationUtterance.seq)
                )
            )
        return entries, utterances

    # -------- ZIP streaming --------

    def stream_zip(self, plan: ExportPlan) -> Iterator[bytes]:
        buf = _ChunkBuffer()
        # archive_path -> (byte_size, sha256). manifest.csv는 실제로 쓴 파일의
        # 크기·해시를 담아야 하므로 모든 파일을 쓴 뒤 마지막에 쓴다.
        digests: dict[str, tuple[int, str]] = {}
        with zipfile.ZipFile(
            buf, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            yield from self._emit_meta(zf, buf, plan)
            yield from self._emit_reports(zf, buf, plan, digests)
            yield from self._emit_conversations(zf, buf, plan, digests)
            yield from self._emit_simulations(zf, buf, plan, digests)
            yield from self._emit_lessonplans(zf, buf, plan, digests)
            yield from self._emit_manifest(zf, buf, plan, digests)
        yield buf.take()

    def _emit_meta(self, zf, buf, plan):
        if "meta" in plan.filters.include:
            zf.writestr("README.txt", build_readme(plan))
            yield buf.take()
            zf.writestr("users.csv", build_users_csv(plan))
            yield buf.take()

    def _emit_manifest(self, zf, buf, plan, digests):
        if "meta" in plan.filters.include:
            zf.writestr("manifest.csv", build_manifest_csv(plan, digests))
            yield buf.take()

    def _emit_reports(self, zf, buf, plan, digests):
        if "reports" not in plan.filters.include:
            return
        for r in plan.reports:
            data, sha = _read_file_or_missing(r.source_path)
            zf.writestr(r.archive_path, data)
            digests[r.archive_path] = _digest(data, sha)
            yield buf.take()

    def _emit_conversations(self, zf, buf, plan, digests):
        if "conversations" not in plan.filters.include:
            return
        for s in plan.sessions:
            payload = _serialize_session_jsonl(
                s, plan.session_messages.get(s.session_id, [])
            )
            zf.writestr(s.archive_path, payload)
            digests[s.archive_path] = _digest(payload)
            yield buf.take()

    def _emit_simulations(self, zf, buf, plan, digests):
        for s in plan.simulations:
            payload = _serialize_simulation_jsonl(
                s, plan.simulation_utterances.get(s.session_id, [])
            )
            zf.writestr(s.archive_path, payload)
            digests[s.archive_path] = _digest(payload)
            yield buf.take()

    def _emit_lessonplans(self, zf, buf, plan, digests):
        if "lessonplans" not in plan.filters.include:
            return
        for lessonplan in plan.lessonplans:
            data, sha = _read_file_or_missing(lessonplan.source_path)
            zf.writestr(lessonplan.archive_path, data)
            digests[lessonplan.archive_path] = _digest(data, sha)
            yield buf.take()


def _date_bounds(
    filters: ExportFilters,
) -> tuple[datetime | None, datetime | None]:
    """관리자(KST) 날짜 범위를 naive UTC [하한, 상한)으로. date_to 포함."""
    lower = upper = None
    if filters.date_from:
        lower = kst_date_start_utc_naive(filters.date_from)
    if filters.date_to:
        upper = kst_date_start_utc_naive(filters.date_to + timedelta(days=1))
    return lower, upper


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


def _digest(data: bytes, sha: str | None = None) -> tuple[int, str]:
    """manifest용 (byte_size, sha256). 원본이 없으면(MISSING) 해시는 비운다."""
    if sha is None:
        sha = hashlib.sha256(data).hexdigest()
    return len(data), "" if sha == "MISSING" else sha


def _serialize_session_jsonl(session_entry, messages) -> bytes:
    lines = []
    for m in messages:
        lines.append(
            json.dumps(
                {
                    "session_id": session_entry.session_id,
                    "message_id": m.id,
                    "role": (
                        m.role.value
                        if hasattr(m.role, "value")
                        else str(m.role)
                    ),
                    "content": m.content,
                    "created_at": (
                        m.created_at.isoformat() if m.created_at else None
                    ),
                },
                ensure_ascii=False,
            )
        )
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _serialize_simulation_jsonl(entry, utterances) -> bytes:
    lines = [
        json.dumps(
            {
                "session_id": entry.session_id,
                "seq": u.seq,
                "phase_idx": u.phase_idx,
                "speaker_type": u.speaker_type,
                "persona_id": u.persona_id,
                "persona_name": entry.persona_names.get(u.persona_id),
                "target_persona_id": u.target_persona_id,
                "content": u.content,
                "structured": u.structured,
                "model_name": u.model_name,
                "latency_ms": u.latency_ms,
                "created_at": (
                    u.created_at.isoformat() if u.created_at else None
                ),
            },
            ensure_ascii=False,
        )
        for u in utterances
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


# -------- CSV / README builders --------


_MANIFEST_COLUMNS = [
    "kind",
    "user_id",
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
    "created_at",
    "last_login_at",
    "n_reports",
    "n_sessions",
    "n_lessonplans",
]


_CSV_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str | None) -> str:
    """Neutralize CSV-injection formula starters in user-controlled strings."""
    if not value:
        return ""
    if value[0] in _CSV_FORMULA_LEADERS:
        return "'" + value
    return value


def build_manifest_csv(
    plan: ExportPlan,
    digests: dict[str, tuple[int, str]] | None = None,
) -> bytes:
    """manifest.csv를 만든다.

    byte_size/sha256은 ``stream_zip``이 실제로 쓴 파일에서 계산한
    ``digests``(archive_path -> (크기, 해시))로 채운다. ZIP에 들어가지 않은
    항목(include에서 빠진 종류)은 빈 칸으로 둔다.
    """
    digests = digests or {}
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_MANIFEST_COLUMNS)
    w.writeheader()
    iter_entries: Iterable = (
        list(plan.reports)
        + list(plan.sessions)
        + list(plan.simulations)
        + list(plan.lessonplans)
    )
    for e in iter_entries:
        size, sha = digests.get(e.archive_path, ("", ""))
        w.writerow(
            {
                "kind": e.kind,
                "user_id": e.user_id,
                "resource_id": e.resource_id,
                "session_id": e.session_id or "",
                "created_at": (
                    e.created_at.isoformat() if e.created_at else ""
                ),
                "original_name": _csv_safe(getattr(e, "original_name", "")),
                "archive_path": e.archive_path,
                "source_status": getattr(e, "source_status", "OK"),
                "byte_size": size,
                "sha256": sha,
            }
        )
    return buf.getvalue().encode("utf-8")


def build_users_csv(plan: ExportPlan) -> bytes:
    counts: dict[int, dict[str, int]] = {
        u.user_id: {"r": 0, "s": 0, "l": 0} for u in plan.users
    }
    for r in plan.reports:
        counts[r.user_id]["r"] += 1
    for s in plan.sessions:
        counts[s.user_id]["s"] += 1
    for lessonplan in plan.lessonplans:
        counts[lessonplan.user_id]["l"] += 1

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_USERS_COLUMNS)
    w.writeheader()
    for u in plan.users:
        w.writerow(
            {
                "user_id": u.user_id,
                "created_at": (
                    u.created_at.isoformat() if u.created_at else ""
                ),
                "last_login_at": (
                    u.last_login_at.isoformat() if u.last_login_at else ""
                ),
                "n_reports": counts[u.user_id]["r"],
                "n_sessions": counts[u.user_id]["s"],
                "n_lessonplans": counts[u.user_id]["l"],
            }
        )
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
        f"  include={sorted(plan.filters.include)}",
        "",
        "Counts:",
        f"  users={len(plan.users)}",
        f"  reports={len(plan.reports)}",
        f"  conversations={len(plan.sessions)}",
        f"  simulations={len(plan.simulations)}",
        f"  lessonplans={len(plan.lessonplans)}",
        "",
        "Layout:",
        "  manifest.csv      마스터 인덱스 (자원→파일 매핑)",
        "  users.csv         사용자 메타데이터 + 자원 개수",
        "  reports/          분석 보고서 (.md)",
        "  conversations/    QnA 세션 대화 (.jsonl)",
        "  simulations/      수업 시뮬레이션 세션 발화 (.jsonl,"
        " include=conversations에 포함)",
        "  lessonplans/      원본 수업 지도안",
        "",
        "파일명 규칙:",
        "  u{user_id}__{resource_kind}_{resource_id}" "__{original_name}.{ext}",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")
