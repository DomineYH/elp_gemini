"""설문 완료 엔드포인트 + 보고서 게이트 403 테스트."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.users import User


def _make_client(user: User):
    async def override_get_user():
        return user

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def uncompleted_user():
    return User(id=1, username="tester", hashed_password="x")


@pytest.mark.asyncio
async def test_complete_survey_records(uncompleted_user):
    assert uncompleted_user.survey_completed_at is None
    async with _make_client(uncompleted_user) as c:
        res = await c.post("/api/survey/complete")
    assert res.status_code == 200
    assert res.json()["survey_completed"] is True
    assert uncompleted_user.survey_completed_at is not None
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_complete_survey_idempotent(uncompleted_user):
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    uncompleted_user.survey_completed_at = fixed
    async with _make_client(uncompleted_user) as c:
        res = await c.post("/api/survey/complete")
    assert res.status_code == 200
    assert uncompleted_user.survey_completed_at == fixed
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_report_json_blocked_without_survey(uncompleted_user):
    async with _make_client(uncompleted_user) as c:
        res = await c.get("/api/lessonplan/reports/10")
    assert res.status_code == 403
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_report_download_blocked_without_survey(uncompleted_user):
    async with _make_client(uncompleted_user) as c:
        res = await c.get("/api/lessonplan/reports/10/download")
    assert res.status_code == 403
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_report_json_allowed_after_survey(tmp_path):
    """완료 사용자는 게이트를 통과한다(403 아님)."""
    from unittest.mock import MagicMock, patch

    completed = User(
        id=1, username="tester", hashed_password="x",
        survey_completed_at=datetime.now(timezone.utc),
    )
    report_file = tmp_path / "r.md"
    report_file.write_text("# 보고서 본문", encoding="utf-8")

    fake_report = MagicMock()
    fake_report.id = 10
    fake_report.lessonplan_filename = "lp.pdf"
    fake_report.lessonplan_original_name = "lp.pdf"
    fake_report.report_filename = "r.md"
    fake_report.report_path = str(report_file)
    fake_report.latency_ms = 1000
    fake_report.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = fake_report

    async def override_get_user():
        return completed

    db = AsyncMock()
    db.execute = AsyncMock(return_value=exec_result)

    async def override_get_db():
        yield db

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/api/lessonplan/reports/10")
    assert res.status_code == 200
    assert res.json()["content"] == "# 보고서 본문"
    app.dependency_overrides.clear()
