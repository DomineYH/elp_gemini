import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.users import User
from app.routers.auth import get_current_user
from app.services.criteria_freshness import ensure_criteria_cache_fresh

client = TestClient(app)


@pytest.fixture
def mock_current_user():
    user = User(id=1, username="testuser", nickname="Test User", is_admin=False)
    return user


@pytest.fixture
def mock_criteria_service():
    # views.py는 DB의 활성 기준·최근 업로드를 읽는다: DB 없이 빈 값으로
    app.dependency_overrides[ensure_criteria_cache_fresh] = lambda: None
    app.dependency_overrides[get_db] = lambda: None
    with (
        patch("app.routers.views.CriteriaRepository") as mock,
        patch(
            "app.routers.views.lessonplan_source.get_latest_upload",
            AsyncMock(return_value=None),
        ),
    ):
        repo = mock.return_value
        repo.get_active_criteria = AsyncMock(return_value=[])
        yield repo
    app.dependency_overrides.pop(ensure_criteria_cache_fresh, None)
    app.dependency_overrides.pop(get_db, None)


def test_dashboard_view_authenticated(mock_current_user, mock_criteria_service):
    # Mock get_current_user dependency
    app.dependency_overrides[get_current_user] = lambda: mock_current_user

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "이전에 진행한 세션" in response.text
    assert "대시보드" in response.text
    assert "/reports/view/${reportId}" in response.text
    assert "/api/lessonplan/reports/${reportId}/download" not in response.text
    assert "normalizeStaticReportUrl" not in response.text
    assert "report.report_path || report.file_path" not in response.text

    # Clean up overrides
    app.dependency_overrides = {}


def test_dashboard_report_links_use_viewer_endpoint(
    mock_current_user, mock_criteria_service
):
    app.dependency_overrides[get_current_user] = lambda: mock_current_user

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "function reportViewerUrl(report)" in response.text
    assert "const reportId = Number(report?.id);" in response.text
    assert "`/reports/view/${reportId}`" in response.text
    assert "const reportUrl = reportViewerUrl(report);" in response.text
    assert 'href="${escapeHtmlAttribute(reportUrl)}"' in response.text

    assert "function reportDownloadUrl(report)" not in response.text
    assert "report.report_path" not in response.text
    assert "report.file_path" not in response.text
    assert "`/static/${" not in response.text

    app.dependency_overrides = {}


def test_close_survey_modal_also_closes_analysis_modal():
    # 설문 모달을 X/배경으로 닫아도 분석 모달이 남아 설문이 반복되지 않게 (#268)
    source = Path("app/templates/user/dashboard.html").read_text(
        encoding="utf-8"
    )
    assert re.search(
        r"function closeSurveyModal\(\) \{(?:\n[^\n]*){0,3}?"
        r"\n\s*closeAnalysisModal\(\);",
        source,
    )
