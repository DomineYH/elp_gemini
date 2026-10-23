from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AnalysisReport
from app.models.users import User
from app.routers.auth import get_current_user

client = TestClient(app)


@pytest.fixture
def mock_current_user():
    return User(
        id=1,
        username="testuser",
        nickname="Test",
        is_admin=False,
    )


@pytest_asyncio.fixture
async def http_client(mock_current_user) -> AsyncIterator[AsyncClient]:
    """격리된 인메모리 DB에 user 1의 보고서 42, user 2의 보고서 43을 둔다."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        session.add_all(
            [
                User(id=1, username="testuser", nickname="Test"),
                User(id=2, username="other", nickname="Other"),
            ]
        )
        for report_id, user_id in ((42, 1), (43, 2)):
            session.add(
                AnalysisReport(
                    id=report_id,
                    user_id=user_id,
                    lessonplan_filename="plan.pdf",
                    report_filename=f"r{report_id}.md",
                    report_path=f"reports/r{report_id}.md",
                )
            )
        await session.commit()

    async def _get_db_override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = lambda: mock_current_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides = {}
        await engine.dispose()


async def test_report_viewer_renders_html_shell(http_client):
    response = await http_client.get("/reports/view/42")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="reportContent"' in response.text
    assert "const REPORT_ID = 42;" in response.text


async def test_report_viewer_other_users_report_returns_404(http_client):
    response = await http_client.get("/reports/view/43")
    assert response.status_code == 404
    assert "const REPORT_ID" not in response.text


async def test_report_viewer_missing_report_returns_404(http_client):
    response = await http_client.get(
        "/reports/view/999", headers={"accept": "application/json"}
    )
    assert response.status_code == 404


def test_report_viewer_unauthenticated_redirects_to_login():
    response = client.get(
        "/reports/view/42",
        follow_redirects=False,
        headers={"accept": "text/html"},
    )
    assert response.status_code in (302, 303, 307)
    assert "/login" in response.headers.get("location", "")


def test_report_viewer_invalid_id_returns_404(mock_current_user):
    app.dependency_overrides[get_current_user] = lambda: mock_current_user
    try:
        response = client.get(
            "/reports/view/0",
            headers={"accept": "application/json"},
        )
    finally:
        app.dependency_overrides = {}
    assert response.status_code == 404


async def test_report_viewer_exposes_download_link(http_client):
    response = await http_client.get("/reports/view/42")

    assert response.status_code == 200
    assert 'href="/api/lessonplan/reports/42/download"' in response.text
    assert "/api/lessonplan/reports/${REPORT_ID}/download" not in response.text


async def test_report_viewer_shows_error_title_on_load_failure(http_client):
    response = await http_client.get("/reports/view/42")

    assert "보고서를 찾을 수 없습니다" in response.text
    assert "status = res.status" in response.text
    assert 'href="/dashboard"' in response.text


def test_admin_report_viewer_shows_error_title_on_load_failure():
    from pathlib import Path

    source = Path("app/templates/admin/admin_report_viewer.html").read_text(
        encoding="utf-8"
    )
    assert "보고서를 찾을 수 없습니다" in source
    assert "status = res.status" in source
    assert 'href="/admin/users"' in source
