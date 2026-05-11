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
