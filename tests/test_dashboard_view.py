from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.users import User
from app.routers.auth import get_current_user

client = TestClient(app)


@pytest.fixture
def mock_current_user():
    user = User(
        id=1,
        username="testuser",
        nickname="Test User",
        email="test@example.com",
        is_admin=False
    )
    return user


@pytest.fixture
def mock_criteria_service():
    with patch("app.routers.views.CriteriaVectorService") as mock:
        service = mock.return_value
        service.list_criteria_documents = AsyncMock(return_value=[])
        yield service


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
