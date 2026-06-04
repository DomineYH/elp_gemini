# tests/test_admin_export_service.py
import csv
import inspect
import io
from datetime import date, datetime
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
async def test_collect_excludes_admin_users(db_session):
    await _seed_user(db_session, user_id=1)
    admin = User(
        id=2, username="adm", nickname="adm", is_admin=True,
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
        id=2, username="adm", nickname="adm", is_admin=True,
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
        created_at=datetime(2026, 4, 30, 23, 59, 59),
    )
    db_session.add(edge)
    await db_session.commit()
    svc = AdminExportService(db_session)
    plan = await svc.collect(
        ExportFilters(date_to=datetime(2026, 4, 30).date())
    )
    assert {r.resource_id for r in plan.reports} == {edge.id}


# ---- CSV shape ----


@pytest.mark.asyncio
async def test_manifest_csv_shape(db_session):
    await _seed_user(db_session, user_id=42)
    db_session.add(AnalysisReport(
        user_id=42,
        lessonplan_filename="42_lp.pdf",
        lessonplan_original_name="1학년_수업지도안.pdf",
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
    db_session.add(AnalysisReport(
        user_id=1,
        lessonplan_filename="u1_a.pdf",
        lessonplan_original_name="a.pdf",
        report_filename="1_a_reports.md",
        report_path="/tmp/a.md",
        created_at=datetime(2026, 3, 1),
    ))
    await db_session.commit()
    # Seed lessonplan under new per-user layout: {user_id}/filename
    user_dir = tmp_path / "1"
    user_dir.mkdir()
    (user_dir / "a.pdf").write_bytes(b"x")
    svc = AdminExportService(
        db_session, lessonplan_base_dir=str(tmp_path)
    )
    plan = await svc.collect(ExportFilters())
    raw = build_users_csv(plan)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert rows[0]["user_id"] == "1"
    assert rows[0]["n_reports"] == "1"
    assert rows[0]["n_sessions"] == "0"
    # Removed columns must not appear
    for col in ("user_email", "role", "region", "tenure", "tenure_kind"):
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
    db_session.add_all([
        ChatMessage(
            session_id=s.id, role=MessageRole.USER,
            content="질문", created_at=same_ts,
        ),
        ChatMessage(
            session_id=s.id, role=MessageRole.ASSISTANT,
            content="답변", created_at=same_ts,
        ),
    ])
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
    db_session.add(AnalysisReport(
        user_id=1,
        lessonplan_filename="1_evil.pdf",
        lessonplan_original_name="=cmd|' /C calc'!A0",
        report_filename="1_evil_reports.md",
        report_path="/tmp/evil.md",
        created_at=datetime(2026, 3, 1),
    ))
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    rows = list(csv.DictReader(
        io.StringIO(build_manifest_csv(plan).decode("utf-8"))
    ))
    report_row = next(r for r in rows if r["kind"] == "report")
    assert report_row["original_name"].startswith("'=")


# ---- lessonplan collection (per-user subdirectory) ----


@pytest.mark.asyncio
async def test_collect_lessonplans_per_user_subdirectory(
    db_session, tmp_path
):
    """Lessonplans live under data/lessonplan/{user_id}/* now."""
    await _seed_user(db_session, user_id=7)
    await db_session.commit()
    user_dir = tmp_path / "7"
    user_dir.mkdir()
    (user_dir / "orphan_지도안.pdf").write_bytes(b"data")
    (user_dir / "another.pdf").write_bytes(b"more")
    svc = AdminExportService(
        db_session, lessonplan_base_dir=str(tmp_path)
    )
    plan = await svc.collect(ExportFilters())
    originals = {entry.original_name for entry in plan.lessonplans}
    assert originals == {"orphan_지도안.pdf", "another.pdf"}


@pytest.mark.asyncio
async def test_collect_lessonplans_per_user_isolation(
    db_session, tmp_path
):
    """User 1's files must not appear under user 2."""
    await _seed_user(db_session, user_id=1)
    await _seed_user(db_session, user_id=2)
    await db_session.commit()
    (tmp_path / "1").mkdir()
    (tmp_path / "1" / "mine.pdf").write_bytes(b"x")
    (tmp_path / "2").mkdir()
    (tmp_path / "2" / "yours.pdf").write_bytes(b"y")
    svc = AdminExportService(
        db_session, lessonplan_base_dir=str(tmp_path)
    )
    plan = await svc.collect(ExportFilters(user_ids=[1]))
    assert {
        entry.original_name for entry in plan.lessonplans
    } == {"mine.pdf"}


@pytest.mark.asyncio
async def test_collect_lessonplans_skipped_when_excluded(
    db_session, tmp_path
):
    await _seed_user(db_session, user_id=1)
    await db_session.commit()
    user_dir = tmp_path / "1"
    user_dir.mkdir()
    (user_dir / "x.pdf").write_bytes(b"x")
    svc = AdminExportService(
        db_session, lessonplan_base_dir=str(tmp_path)
    )
    plan = await svc.collect(
        ExportFilters(include=frozenset({"reports", "meta"}))
    )
    assert plan.lessonplans == []


@pytest.mark.asyncio
async def test_collect_lessonplans_marks_deleted_report_source_missing(
    tmp_path
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
    rows = list(csv.DictReader(
        io.StringIO(build_manifest_csv(plan).decode("utf-8"))
    ))
    lessonplan_row = next(
        r for r in rows
        if r["kind"] == "lessonplan"
        and r["original_name"] == "deleted.pdf"
    )
    assert lessonplan_row["source_status"] == "MISSING"


@pytest.mark.asyncio
async def test_collect_lessonplans_resolves_dashboard_upload_source(
    db_session, tmp_path, monkeypatch
):
    await _seed_user(db_session, user_id=1)
    upload_dir = tmp_path / "app" / "static" / "uploads"
    upload_dir.mkdir(parents=True)
    filename = "u1_20260101000000_plan.pdf"
    upload_file = upload_dir / filename
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
    db_session.add(AnalysisReport(
        user_id=1,
        lessonplan_filename=filename,
        lessonplan_original_name="plan.pdf",
        report_filename="r.md",
        report_path=str(tmp_path / "r.md"),
        upload_id=upload.id,
        created_at=datetime(2026, 3, 1),
    ))
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())

    matches = [
        entry for entry in plan.lessonplans
        if entry.original_name == "plan.pdf"
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
    legacy_dir.mkdir(parents=True)
    static_uploads_dir = tmp_path / "app" / "static" / "uploads"
    static_uploads_dir.mkdir(parents=True)
    filename = "u1_20260101000000_legacy.pdf"
    legacy_file = legacy_dir / filename
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
    db_session.add(AnalysisReport(
        user_id=1,
        lessonplan_filename=filename,
        lessonplan_original_name="legacy.pdf",
        report_filename="r.md",
        report_path=str(tmp_path / "r.md"),
        upload_id=upload.id,
        created_at=datetime(2026, 3, 1),
    ))
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
        entry for entry in plan.lessonplans
        if entry.original_name == "legacy.pdf"
    ]
    assert len(matches) == 1
    lessonplan = matches[0]
    assert Path(lessonplan.source_path).resolve() == legacy_file
    assert lessonplan.source_status == "OK"


@pytest.mark.asyncio
async def test_collect_lessonplans_includes_upload_without_report(
    tmp_path
):
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

    svc = AdminExportService(
        Db([upload]), static_uploads_dir=str(upload_dir)
    )
    lessonplans = await svc._collect_lessonplans([user], ExportFilters())

    matches = [
        entry for entry in lessonplans
        if entry.original_name == "unanalyzed.pdf"
    ]
    assert len(matches) == 1
    lessonplan = matches[0]
    assert Path(lessonplan.source_path).resolve() == upload_file
    assert lessonplan.source_status == "OK"
