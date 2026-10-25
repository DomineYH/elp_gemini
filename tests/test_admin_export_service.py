# tests/test_admin_export_service.py
import csv
import inspect
import io
import os
import time
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_session import SimulationSession
from app.models.users import User
from app.schemas.admin_export import ExportFilters
from app.services.admin_export_service import (
    AdminExportService,
    ExportPlan,
    UserContext,
    build_manifest_csv,
    build_readme,
    build_users_csv,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _seed_user(session, *, user_id):
    """Seed a bare user — no email, no profile."""
    user = User(
        id=user_id,
        username=f"u{user_id}",
        nickname=f"n{user_id}",
    )
    session.add(user)
    await session.commit()
    return user


# ---- user collection ----


@pytest.mark.asyncio
async def test_collect_filters_by_user_ids(db_session):
    await _seed_user(db_session, user_id=1)
    await _seed_user(db_session, user_id=2)
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters(user_ids=[2]))
    assert {u.user_id for u in plan.users} == {2}


@pytest.mark.asyncio
async def test_collect_includes_sessions_and_messages(db_session):
    await _seed_user(db_session, user_id=1)
    s = ChatSession(user_id=1, title="t1")
    db_session.add(s)
    await db_session.flush()
    db_session.add_all(
        [
            ChatMessage(session_id=s.id, role=MessageRole.USER, content="hi"),
            ChatMessage(
                session_id=s.id,
                role=MessageRole.ASSISTANT,
                content="hello",
            ),
        ]
    )
    await db_session.commit()
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    assert len(plan.sessions) == 1
    assert plan.sessions[0].message_count == 2


@pytest.mark.asyncio
async def test_collect_excludes_admin_users(db_session):
    await _seed_user(db_session, user_id=1)
    admin = User(
        id=2,
        username="adm",
        nickname="adm",
        is_admin=True,
    )
    db_session.add(admin)
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    assert {u.user_id for u in plan.users} == {1}


@pytest.mark.asyncio
async def test_collect_excludes_admin_even_in_user_ids(db_session):
    await _seed_user(db_session, user_id=1)
    admin = User(
        id=2,
        username="adm",
        nickname="adm",
        is_admin=True,
    )
    db_session.add(admin)
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters(user_ids=[1, 2]))
    assert {u.user_id for u in plan.users} == {1}


# ---- date filters ----


@pytest.mark.asyncio
async def test_collect_filters_by_date_range(db_session):
    await _seed_user(db_session, user_id=1)
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
async def test_collect_filters_date_to_inclusive(db_session):
    await _seed_user(db_session, user_id=1)
    edge = AnalysisReport(
        user_id=1,
        lessonplan_filename="1_edge.pdf",
        lessonplan_original_name="edge.pdf",
        report_filename="1_edge_reports.md",
        report_path="/tmp/edge.md",
        # KST 4/30 23:59:59 (DB created_at은 naive UTC)
        created_at=datetime(2026, 4, 30, 14, 59, 59),
    )
    db_session.add(edge)
    await db_session.commit()
    svc = AdminExportService(db_session)
    plan = await svc.collect(
        ExportFilters(date_to=datetime(2026, 4, 30).date())
    )
    assert {r.resource_id for r in plan.reports} == {edge.id}


# KST 10-22 자정 = UTC 10-21 15:00. 그 ±1분 (#211)
_KST_EDGE = {
    "before": datetime(2026, 10, 21, 14, 59),
    "after": datetime(2026, 10, 21, 15, 1),
}


@contextmanager
def _server_tz(tz):
    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = tz
        time.tzset()
        yield
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


@pytest.mark.asyncio
async def test_collect_date_filters_use_kst_midnight(db_session, tmp_path):
    await _seed_user(db_session, user_id=1)
    for tag, at in _KST_EDGE.items():
        upload = LessonPlanUpload(
            user_id=1,
            filename=f"{tag}_up.pdf",
            original_filename=f"{tag}_up.pdf",
            created_at=at,
        )
        db_session.add(upload)
        await db_session.flush()
        db_session.add_all(
            [
                AnalysisReport(
                    user_id=1,
                    lessonplan_filename=f"{tag}_rp.pdf",
                    lessonplan_original_name=f"{tag}_rp.pdf",
                    report_filename=f"{tag}.md",
                    report_path=f"/tmp/{tag}.md",
                    created_at=at,
                ),
                ChatSession(user_id=1, title=tag, created_at=at, updated_at=at),
                SimulationSession(
                    user_id=1,
                    upload_id=upload.id,
                    persona_count=1,
                    model_name="m",
                    created_at=at,
                ),
            ]
        )
    await db_session.commit()
    svc = AdminExportService(db_session, lessonplan_base_dir=str(tmp_path))
    cases = (
        (ExportFilters(date_from=date(2026, 10, 22)), "after"),
        (ExportFilters(date_to=date(2026, 10, 21)), "before"),
    )
    for tz in ("UTC", "Asia/Seoul"):
        with _server_tz(tz):
            for filters, tag in cases:
                plan = await svc.collect(filters)
                at = _KST_EDGE[tag]
                for entries in (plan.reports, plan.sessions, plan.simulations):
                    assert [e.created_at for e in entries] == [at], (tz, tag)
                assert {e.original_name for e in plan.lessonplans} == {
                    f"{tag}_rp.pdf",
                    f"{tag}_up.pdf",
                }, (tz, tag)


@pytest.mark.asyncio
async def test_collect_lessonplan_mtime_uses_kst_midnight(db_session, tmp_path):
    await _seed_user(db_session, user_id=1)
    user_dir = tmp_path / "1"
    user_dir.mkdir()
    for tag, at in _KST_EDGE.items():
        fpath = user_dir / f"{tag}.pdf"
        fpath.write_bytes(b"x")
        ts = at.replace(tzinfo=timezone.utc).timestamp()
        os.utime(fpath, (ts, ts))
    svc = AdminExportService(db_session, lessonplan_base_dir=str(tmp_path))
    cases = (
        (date(2026, 10, 22), None, "after"),
        (None, date(2026, 10, 21), "before"),
    )
    for tz in ("UTC", "Asia/Seoul"):
        with _server_tz(tz):
            for date_from, date_to, tag in cases:
                plan = await svc.collect(
                    ExportFilters(
                        date_from=date_from,
                        date_to=date_to,
                        include=frozenset({"lessonplans"}),
                    )
                )
                # mtime도 DB created_at처럼 naive UTC로 기록된다
                assert [
                    (e.original_name, e.created_at) for e in plan.lessonplans
                ] == [(f"{tag}.pdf", _KST_EDGE[tag])], (tz, tag)


# ---- CSV shape ----


@pytest.mark.asyncio
async def test_manifest_csv_shape(db_session):
    await _seed_user(db_session, user_id=42)
    db_session.add(
        AnalysisReport(
            user_id=42,
            lessonplan_filename="42_lp.pdf",
            lessonplan_original_name="1학년_수업지도안.pdf",
            report_filename="42_lp_reports.md",
            report_path="/tmp/r.md",
            created_at=datetime(2026, 3, 1, 10, 22, 5),
        )
    )
    await db_session.commit()
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())

    raw = build_manifest_csv(plan)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert any(
        r["kind"] == "report"
        and r["user_id"] == "42"
        and r["archive_path"].startswith("reports/u00042__")
        for r in rows
    )
    # Removed columns must not appear
    header = rows[0] if rows else {}
    for col in ("user_email", "role", "region", "tenure", "tenure_kind"):
        assert col not in header, f"{col} should not be in manifest CSV"


@pytest.mark.asyncio
async def test_users_csv_counts(db_session, tmp_path):
    await _seed_user(db_session, user_id=1)
    db_session.add(
        AnalysisReport(
            user_id=1,
            lessonplan_filename="u1_a.pdf",
            lessonplan_original_name="a.pdf",
            report_filename="1_a_reports.md",
            report_path="/tmp/a.md",
            created_at=datetime(2026, 3, 1),
        )
    )
    await db_session.commit()
    # Seed lessonplan under new per-user layout: {user_id}/filename
    user_dir = tmp_path / "1"
    user_dir.mkdir()
    (user_dir / "a.pdf").write_bytes(b"x")
    svc = AdminExportService(db_session, lessonplan_base_dir=str(tmp_path))
    plan = await svc.collect(ExportFilters())
    raw = build_users_csv(plan)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert list(rows[0]) == [
        "user_id",
        "username",
        "created_at",
        "n_reports",
        "n_sessions",
        "n_lessonplans",
    ]
    assert rows[0]["user_id"] == "1"
    assert rows[0]["username"] == "u1"
    assert rows[0]["n_reports"] == "1"
    assert rows[0]["n_sessions"] == "0"
    # Removed columns must not appear
    for col in (
        "user_email",
        "role",
        "region",
        "tenure",
        "tenure_kind",
        "last_login_at",
    ):
        assert col not in rows[0], f"{col} should not be in users CSV"


# ---- readme ----


@pytest.mark.asyncio
async def test_readme_mentions_filters(db_session):
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    text = build_readme(plan).decode("utf-8")
    assert "manifest.csv" in text
    # Removed filter fields must not appear
    assert "role=" not in text
    assert "region=" not in text
    assert "career_min=" not in text
    assert "career_max=" not in text


# ---- message ordering ----


@pytest.mark.asyncio
async def test_session_messages_stable_order_on_tied_timestamps(
    db_session,
):
    await _seed_user(db_session, user_id=1)
    s = ChatSession(user_id=1, title="t1")
    db_session.add(s)
    await db_session.flush()
    same_ts = datetime(2026, 3, 1, 10, 0, 0)
    db_session.add_all(
        [
            ChatMessage(
                session_id=s.id,
                role=MessageRole.USER,
                content="질문",
                created_at=same_ts,
            ),
            ChatMessage(
                session_id=s.id,
                role=MessageRole.ASSISTANT,
                content="답변",
                created_at=same_ts,
            ),
        ]
    )
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    ordered = plan.session_messages[s.id]
    assert [m.id for m in ordered] == sorted(m.id for m in ordered)
    assert ordered[0].role == MessageRole.USER
    assert ordered[1].role == MessageRole.ASSISTANT


# ---- CSV injection defense ----


@pytest.mark.asyncio
async def test_manifest_csv_neutralizes_formula_filenames(db_session):
    await _seed_user(db_session, user_id=1)
    db_session.add(
        AnalysisReport(
            user_id=1,
            lessonplan_filename="1_evil.pdf",
            lessonplan_original_name="=cmd|' /C calc'!A0",
            report_filename="1_evil_reports.md",
            report_path="/tmp/evil.md",
            created_at=datetime(2026, 3, 1),
        )
    )
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    rows = list(
        csv.DictReader(io.StringIO(build_manifest_csv(plan).decode("utf-8")))
    )
    report_row = next(r for r in rows if r["kind"] == "report")
    assert report_row["original_name"].startswith("'=")


# ---- lessonplan collection (per-user subdirectory) ----


@pytest.mark.asyncio
async def test_collect_lessonplans_per_user_subdirectory(db_session, tmp_path):
    """Lessonplans live under data/lessonplan/{user_id}/* now."""
    await _seed_user(db_session, user_id=7)
    await db_session.commit()
    user_dir = tmp_path / "7"
    user_dir.mkdir()
    (user_dir / "orphan_지도안.pdf").write_bytes(b"data")
    (user_dir / "another.pdf").write_bytes(b"more")
    svc = AdminExportService(db_session, lessonplan_base_dir=str(tmp_path))
    plan = await svc.collect(ExportFilters())
    originals = {entry.original_name for entry in plan.lessonplans}
    assert originals == {"orphan_지도안.pdf", "another.pdf"}


@pytest.mark.asyncio
async def test_collect_lessonplans_per_user_isolation(db_session, tmp_path):
    """User 1's files must not appear under user 2."""
    await _seed_user(db_session, user_id=1)
    await _seed_user(db_session, user_id=2)
    await db_session.commit()
    (tmp_path / "1").mkdir()
    (tmp_path / "1" / "mine.pdf").write_bytes(b"x")
    (tmp_path / "2").mkdir()
    (tmp_path / "2" / "yours.pdf").write_bytes(b"y")
    svc = AdminExportService(db_session, lessonplan_base_dir=str(tmp_path))
    plan = await svc.collect(ExportFilters(user_ids=[1]))
    assert {entry.original_name for entry in plan.lessonplans} == {"mine.pdf"}


@pytest.mark.asyncio
async def test_collect_lessonplans_skipped_when_excluded(db_session, tmp_path):
    await _seed_user(db_session, user_id=1)
    await db_session.commit()
    user_dir = tmp_path / "1"
    user_dir.mkdir()
    (user_dir / "x.pdf").write_bytes(b"x")
    svc = AdminExportService(db_session, lessonplan_base_dir=str(tmp_path))
    plan = await svc.collect(
        ExportFilters(include=frozenset({"reports", "meta"}))
    )
    assert plan.lessonplans == []


@pytest.mark.asyncio
async def test_collect_lessonplans_marks_deleted_report_source_missing(
    tmp_path,
):
    class Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class Db:
        def __init__(self):
            self._results = [[report], []]

        async def execute(self, stmt):
            return Result(self._results.pop(0))

    user = UserContext(
        user_id=1,
        filename_prefix="u00001",
        username="u1",
    )
    report = AnalysisReport(
        id=10,
        user_id=1,
        lessonplan_filename="deleted.pdf",
        lessonplan_original_name="deleted.pdf",
        report_filename="deleted_reports.md",
        report_path="/tmp/deleted_report.md",
        created_at=datetime(2026, 3, 1),
    )

    svc = AdminExportService(
        Db(), lessonplan_base_dir=str(tmp_path / "missing")
    )
    result = svc._collect_lessonplans([user], ExportFilters())
    lessonplans = await result if inspect.isawaitable(result) else result
    plan = ExportPlan(users=[user], lessonplans=lessonplans)
    rows = list(
        csv.DictReader(io.StringIO(build_manifest_csv(plan).decode("utf-8")))
    )
    lessonplan_row = next(
        r
        for r in rows
        if r["kind"] == "lessonplan" and r["original_name"] == "deleted.pdf"
    )
    assert lessonplan_row["source_status"] == "MISSING"


@pytest.mark.asyncio
async def test_collect_lessonplans_resolves_dashboard_upload_source(
    db_session, tmp_path, monkeypatch
):
    await _seed_user(db_session, user_id=1)
    upload_dir = tmp_path / "app" / "static" / "uploads"
    user_upload_dir = upload_dir / "1"
    user_upload_dir.mkdir(parents=True)
    filename = "u1_20260101000000_plan.pdf"
    upload_file = user_upload_dir / filename
    upload_file.write_bytes(b"%PDF-1.4\n")
    monkeypatch.chdir(tmp_path)

    upload = LessonPlanUpload(
        user_id=1,
        filename=filename,
        original_filename="plan.pdf",
        file_hash="a" * 64,
    )
    db_session.add(upload)
    await db_session.flush()
    db_session.add(
        AnalysisReport(
            user_id=1,
            lessonplan_filename=filename,
            lessonplan_original_name="plan.pdf",
            report_filename="r.md",
            report_path=str(tmp_path / "r.md"),
            upload_id=upload.id,
            created_at=datetime(2026, 3, 1),
        )
    )
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())

    matches = [
        entry for entry in plan.lessonplans if entry.original_name == "plan.pdf"
    ]
    assert len(matches) == 1
    lessonplan = matches[0]
    assert Path(lessonplan.source_path).resolve() == upload_file
    assert lessonplan.source_status == "OK"


@pytest.mark.asyncio
async def test_collect_lessonplans_resolves_synthetic_upload_legacy_source(
    db_session, tmp_path
):
    await _seed_user(db_session, user_id=1)
    legacy_dir = tmp_path / "data" / "lessonplan"
    user_legacy_dir = legacy_dir / "1"
    user_legacy_dir.mkdir(parents=True)
    static_uploads_dir = tmp_path / "app" / "static" / "uploads"
    static_uploads_dir.mkdir(parents=True)
    filename = "u1_20260101000000_legacy.pdf"
    legacy_file = user_legacy_dir / filename
    legacy_file.write_bytes(b"%PDF-1.4\n")
    assert not (static_uploads_dir / filename).exists()

    upload = LessonPlanUpload(
        user_id=1,
        filename=filename,
        original_filename="legacy.pdf",
        file_hash=None,
    )
    db_session.add(upload)
    await db_session.flush()
    db_session.add(
        AnalysisReport(
            user_id=1,
            lessonplan_filename=filename,
            lessonplan_original_name="legacy.pdf",
            report_filename="r.md",
            report_path=str(tmp_path / "r.md"),
            upload_id=upload.id,
            created_at=datetime(2026, 3, 1),
        )
    )
    await db_session.commit()

    svc = AdminExportService(
        db_session,
        lessonplan_base_dir=str(legacy_dir),
        static_uploads_dir=str(static_uploads_dir),
    )
    plan = await svc.collect(
        ExportFilters(
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 1),
        )
    )

    matches = [
        entry
        for entry in plan.lessonplans
        if entry.original_name == "legacy.pdf"
    ]
    assert len(matches) == 1
    lessonplan = matches[0]
    assert Path(lessonplan.source_path).resolve() == legacy_file
    assert lessonplan.source_status == "OK"


@pytest.mark.asyncio
async def test_collect_lessonplans_includes_upload_without_report(tmp_path):
    class Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class Db:
        def __init__(self, uploads):
            self._results = [[], uploads]

        async def execute(self, stmt):
            return Result(self._results.pop(0))

    user = UserContext(
        user_id=1,
        filename_prefix="u00001",
        username="u1",
    )
    upload_dir = tmp_path / "static-uploads"
    upload_dir.mkdir(parents=True)
    filename = "u1_20260101000000_unanalyzed.pdf"
    upload_file = upload_dir / filename
    upload_file.write_bytes(b"%PDF-1.4\n")

    upload = LessonPlanUpload(
        id=11,
        user_id=1,
        filename=filename,
        original_filename="unanalyzed.pdf",
        file_hash="b" * 64,
        created_at=datetime(2026, 3, 2),
    )

    svc = AdminExportService(Db([upload]), static_uploads_dir=str(upload_dir))
    lessonplans = await svc._collect_lessonplans([user], ExportFilters())

    matches = [
        entry
        for entry in lessonplans
        if entry.original_name == "unanalyzed.pdf"
    ]
    assert len(matches) == 1
    lessonplan = matches[0]
    assert Path(lessonplan.source_path).resolve() == upload_file
    assert lessonplan.source_status == "OK"


def _manifest_rows(plan) -> dict[str, dict]:
    rows = csv.DictReader(io.StringIO(build_manifest_csv(plan).decode()))
    return {r["archive_path"]: r for r in rows}


@pytest.mark.asyncio
async def test_report_and_lessonplan_share_upload_number(db_session, tmp_path):
    await _seed_user(db_session, user_id=1)
    upload = LessonPlanUpload(
        user_id=1,
        filename="u1_20260101000000_plan.pdf",
        original_filename="plan.pdf",
        file_hash="c" * 64,
    )
    db_session.add(upload)
    await db_session.flush()
    report = AnalysisReport(
        user_id=1,
        # 파일명이 업로드 행과 달라도 upload_id로 중복을 막는다
        lessonplan_filename="plan.pdf",
        lessonplan_original_name="plan.pdf",
        report_filename="r.md",
        report_path=str(tmp_path / "r.md"),
        upload_id=upload.id,
    )
    db_session.add(report)
    await db_session.commit()

    plan = await AdminExportService(db_session).collect(ExportFilters())

    assert [e.archive_path for e in plan.reports] == [
        f"reports/u00001__report_{upload.id}__plan.md"
    ]
    assert [e.archive_path for e in plan.lessonplans] == [
        f"lessonplans/u00001__lessonplan_{upload.id}__plan.pdf"
    ]
    assert plan.reports[0].resource_id == report.id
    rows = _manifest_rows(plan)
    assert [r["upload_id"] for r in rows.values()] == [str(upload.id)] * 2


@pytest.mark.asyncio
async def test_report_without_upload_falls_back_to_report_number(
    db_session, tmp_path
):
    await _seed_user(db_session, user_id=1)
    report = AnalysisReport(
        user_id=1,
        lessonplan_filename="old.pdf",
        lessonplan_original_name="old.pdf",
        report_filename="r.md",
        report_path=str(tmp_path / "r.md"),
        upload_id=None,
    )
    db_session.add(report)
    await db_session.commit()

    plan = await AdminExportService(db_session).collect(ExportFilters())

    assert [e.archive_path for e in plan.reports] == [
        f"reports/u00001__report_r{report.id}__old.md"
    ]
    assert [e.archive_path for e in plan.lessonplans] == [
        f"lessonplans/u00001__lessonplan_r{report.id}__old.pdf"
    ]
    rows = _manifest_rows(plan)
    assert [r["upload_id"] for r in rows.values()] == ["", ""]


@pytest.mark.asyncio
async def test_drifted_report_filename_falls_back_to_upload_file(
    db_session, tmp_path
):
    await _seed_user(db_session, user_id=1)
    upload_dir = tmp_path / "static-uploads"
    (upload_dir / "1").mkdir(parents=True)
    filename = "u1_20260101000000_plan.pdf"
    upload_file = upload_dir / "1" / filename
    pdf = b"%PDF-1.4\nplan\n"
    upload_file.write_bytes(pdf)
    upload = LessonPlanUpload(
        user_id=1,
        filename=filename,
        original_filename="plan.pdf",
        file_hash="d" * 64,
    )
    db_session.add(upload)
    await db_session.flush()
    db_session.add(
        AnalysisReport(
            user_id=1,
            lessonplan_filename="plan.pdf",  # 옛 행: 업로드 파일명과 다르다
            lessonplan_original_name="plan.pdf",
            report_filename="r.md",
            report_path=str(tmp_path / "r.md"),
            upload_id=upload.id,
        )
    )
    await db_session.commit()

    svc = AdminExportService(
        db_session,
        lessonplan_base_dir=str(tmp_path / "no-legacy"),
        static_uploads_dir=str(upload_dir),
    )
    plan = await svc.collect(ExportFilters())

    assert len(plan.lessonplans) == 1
    entry = plan.lessonplans[0]
    assert entry.source_status == "OK"
    assert Path(entry.source_path).resolve() == upload_file.resolve()
    zf = zipfile.ZipFile(io.BytesIO(b"".join(svc.stream_zip(plan))))
    assert zf.read(entry.archive_path) == pdf


@pytest.mark.asyncio
async def test_conversation_names_use_upload_number(db_session):
    await _seed_user(db_session, user_id=1)
    upload = LessonPlanUpload(
        user_id=1,
        filename="u1_20260101000000_plan.pdf",
        original_filename="plan.pdf",
        file_hash="e" * 64,
    )
    db_session.add(upload)
    await db_session.flush()
    linked = ChatSession(user_id=1, title="t1", upload_id=upload.id)
    old = ChatSession(user_id=1, title="old")
    db_session.add_all([linked, old])
    await db_session.commit()

    plan = await AdminExportService(db_session).collect(ExportFilters())

    by_id = {e.session_id: e for e in plan.sessions}
    linked_path = f"conversations/u00001__conversation_{upload.id}__plan__s{linked.id}.jsonl"
    old_path = f"conversations/u00001__conversation_s{old.id}.jsonl"
    assert by_id[linked.id].archive_path == linked_path
    assert by_id[old.id].archive_path == old_path
    assert by_id[linked.id].resource_id == linked.id
    assert by_id[old.id].resource_id == old.id
    rows = _manifest_rows(plan)
    assert rows[linked_path]["upload_id"] == str(upload.id)
    assert rows[old_path]["upload_id"] == ""
