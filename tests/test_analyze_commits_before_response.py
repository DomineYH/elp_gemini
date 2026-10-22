"""analyze 성공 응답 전에 보고서 행이 커밋되어야 한다 (#220).

FastAPI 0.121은 yield 의존성 종료(get_db의 commit)를 응답 뒤에 돌린다.
라우트가 직접 commit하지 않으면 클라이언트의 즉시 목록 조회가 0건을 읽는다.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies import get_current_user
from app.models.analysis_reports import AnalysisReport
from app.models.users import User
from app.routers import lessonplan_analysis

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    # teardown에서 commit하지 않는다: 라우트가 응답 전에 커밋해야만 남는다
    async with SessionLocal() as database:
        yield database


@pytest_asyncio.fixture
async def user():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        row = User(
            username="report_user",
            nickname="Report User",
            hashed_password="hashed",
            is_admin=False,
        )
        db.add(row)
        await db.commit()
    yield row
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(user):
    test_app = FastAPI()
    test_app.include_router(lessonplan_analysis.router)
    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_analyze_commits_report_before_response(
    client, user, monkeypatch
):
    async def fake_analyze(self, session_id, user_id):
        self.db.add(
            AnalysisReport(
                user_id=user_id,
                lessonplan_filename="1_plan.pdf",
                report_filename="1_plan_reports.md",
                report_path="reports/1_plan_reports.md",
            )
        )
        await self.db.flush()
        return {"success": True, "report": "# 보고서"}

    monkeypatch.setattr(
        lessonplan_analysis.LessonPlanAnalysisService,
        "analyze_lesson_plan",
        fake_analyze,
    )

    response = await client.post(
        "/api/lessonplan/analyze", json={"session_id": 1}
    )
    assert response.status_code == 200, response.text

    async with SessionLocal() as db:
        rows = (await db.execute(select(AnalysisReport))).scalars().all()
    assert [r.user_id for r in rows] == [user.id]
