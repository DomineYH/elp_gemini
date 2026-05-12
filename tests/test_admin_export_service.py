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
async def test_collect_filters_date_to_inclusive(db_session):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
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
        and r["user_email"] == "kim@example.com"
        and r["role"] == "teacher"
        and r["region"] == "서울"
        and r["tenure"] == "12"
        and r["tenure_kind"] == "years"
        and r["archive_path"].startswith("reports/T-서울-12y__u00042__")
        for r in rows
    )


@pytest.mark.asyncio
async def test_users_csv_counts(db_session, tmp_path):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
    db_session.add(AnalysisReport(
        user_id=1,
        lessonplan_filename="u1_a.pdf",
        lessonplan_original_name="a.pdf",
        report_filename="1_a_reports.md",
        report_path="/tmp/a.md",
        created_at=datetime(2026, 3, 1),
    ))
    (tmp_path / "u1_a.pdf").write_bytes(b"x")
    await db_session.commit()
    svc = AdminExportService(
        db_session, lessonplan_base_dir=str(tmp_path)
    )
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


@pytest.mark.asyncio
async def test_session_messages_stable_order_on_tied_timestamps(
    db_session,
):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
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


@pytest.mark.asyncio
async def test_manifest_csv_neutralizes_formula_filenames(db_session):
    await _seed_user(
        db_session, user_id=1, email="=hacker@x.com",
        role="teacher", region="서울", tenure=5,
    )
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
    assert report_row["user_email"].startswith("'=")


@pytest.mark.asyncio
async def test_users_csv_neutralizes_formula_email(db_session):
    await _seed_user(
        db_session, user_id=1, email="+evil@x.com",
        role="teacher", region="서울", tenure=5,
    )
    await db_session.commit()
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    rows = list(csv.DictReader(
        io.StringIO(build_users_csv(plan).decode("utf-8"))
    ))
    assert rows[0]["user_email"].startswith("'+")


@pytest.mark.asyncio
async def test_collect_excludes_admin_users(db_session):
    await _seed_user(
        db_session, user_id=1, email="t@x.com",
        role="teacher", region="서울", tenure=5,
    )
    admin = User(
        id=2, username="adm", nickname="adm",
        email="adm@x.com", is_admin=True,
    )
    db_session.add(admin)
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters())
    assert {u.user_id for u in plan.users} == {1}


@pytest.mark.asyncio
async def test_collect_excludes_admin_even_in_user_ids(db_session):
    await _seed_user(
        db_session, user_id=1, email="t@x.com",
        role="teacher", region="서울", tenure=5,
    )
    admin = User(
        id=2, username="adm", nickname="adm",
        email="adm@x.com", is_admin=True,
    )
    db_session.add(admin)
    await db_session.commit()

    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters(user_ids=[1, 2]))
    assert {u.user_id for u in plan.users} == {1}


@pytest.mark.asyncio
async def test_collect_career_filter_teacher(db_session):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=3,
    )
    await _seed_user(
        db_session, user_id=2, email="b@x.com",
        role="teacher", region="서울", tenure=10,
    )
    await _seed_user(
        db_session, user_id=3, email="c@x.com",
        role="teacher", region="서울", tenure=20,
    )
    svc = AdminExportService(db_session)
    plan = await svc.collect(
        ExportFilters(career_min=5, career_max=15)
    )
    assert {u.user_id for u in plan.users} == {2}


@pytest.mark.asyncio
async def test_collect_career_filter_preservice(db_session):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="preservice_teacher", region="부산", tenure=1,
    )
    await _seed_user(
        db_session, user_id=2, email="b@x.com",
        role="preservice_teacher", region="부산", tenure=3,
    )
    svc = AdminExportService(db_session)
    plan = await svc.collect(ExportFilters(career_min=2))
    assert {u.user_id for u in plan.users} == {2}


@pytest.mark.asyncio
async def test_collect_career_filter_unions_both_roles(db_session):
    await _seed_user(
        db_session, user_id=1, email="t@x.com",
        role="teacher", region="서울", tenure=4,
    )
    await _seed_user(
        db_session, user_id=2, email="p@x.com",
        role="preservice_teacher", region="부산", tenure=4,
    )
    await _seed_user(
        db_session, user_id=3, email="t2@x.com",
        role="teacher", region="서울", tenure=15,
    )
    svc = AdminExportService(db_session)
    plan = await svc.collect(
        ExportFilters(career_min=3, career_max=5)
    )
    assert {u.user_id for u in plan.users} == {1, 2}


@pytest.mark.asyncio
async def test_collect_lessonplans_includes_orphan_uploads(
    db_session, tmp_path
):
    """보고서가 없는 사용자도 업로드한 지도안 파일이 ZIP에 포함되어야 한다."""
    await _seed_user(
        db_session, user_id=7, email="solo@x.com",
        role="teacher", region="서울", tenure=3,
    )
    await db_session.commit()
    (tmp_path / "u7_orphan_지도안.pdf").write_bytes(b"data")
    (tmp_path / "u7_another.pdf").write_bytes(b"more")
    svc = AdminExportService(
        db_session, lessonplan_base_dir=str(tmp_path)
    )
    plan = await svc.collect(ExportFilters())
    originals = {l.original_name for l in plan.lessonplans}
    assert originals == {"orphan_지도안.pdf", "another.pdf"}


@pytest.mark.asyncio
async def test_collect_lessonplans_respects_username_prefix(
    db_session, tmp_path
):
    """다른 사용자의 파일은 포함되지 않아야 한다."""
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
    await _seed_user(
        db_session, user_id=2, email="b@x.com",
        role="teacher", region="서울", tenure=5,
    )
    await db_session.commit()
    (tmp_path / "u1_mine.pdf").write_bytes(b"x")
    (tmp_path / "u2_yours.pdf").write_bytes(b"y")
    svc = AdminExportService(
        db_session, lessonplan_base_dir=str(tmp_path)
    )
    plan = await svc.collect(ExportFilters(user_ids=[1]))
    assert {l.original_name for l in plan.lessonplans} == {"mine.pdf"}


@pytest.mark.asyncio
async def test_collect_lessonplans_skipped_when_excluded(
    db_session, tmp_path
):
    await _seed_user(
        db_session, user_id=1, email="a@x.com",
        role="teacher", region="서울", tenure=5,
    )
    await db_session.commit()
    (tmp_path / "u1_x.pdf").write_bytes(b"x")
    svc = AdminExportService(
        db_session, lessonplan_base_dir=str(tmp_path)
    )
    plan = await svc.collect(
        ExportFilters(include=frozenset({"reports", "meta"}))
    )
    assert plan.lessonplans == []


@pytest.mark.asyncio
async def test_readme_mentions_career_filters(db_session):
    svc = AdminExportService(db_session)
    plan = await svc.collect(
        ExportFilters(career_min=3, career_max=10)
    )
    text = build_readme(plan).decode("utf-8")
    assert "career_min=3" in text
    assert "career_max=10" in text
