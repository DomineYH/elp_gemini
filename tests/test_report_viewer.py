from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.users import User
from app.routers.auth import get_current_user

client = TestClient(app)


@pytest.fixture
def mock_current_user():
    return User(
        id=1, username="testuser", nickname="Test",
        email="t@example.com", is_admin=False,
    )


def test_report_viewer_renders_html_shell(mock_current_user):
    app.dependency_overrides[get_current_user] = lambda: mock_current_user
    try:
        response = client.get("/reports/view/42")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="reportContent"' in response.text
    assert "const REPORT_ID = 42;" in response.text
