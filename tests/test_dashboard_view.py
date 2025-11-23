import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.models.users import User
from app.routers.auth import get_current_user
from datetime import datetime

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
def mock_storage_service():
    with patch("app.routers.views.LessonPlanStorageService") as mock:
        service = mock.return_value
        service.list_lessonplans.return_value = [
            {
                "filename": "testuser_doc1.pdf",
                "original_filename": "doc1.pdf",
                "file_path": "/tmp/testuser_doc1.pdf",
                "size": 1024,
                "created_at": datetime.now().isoformat()
            }
        ]
        yield service

def test_dashboard_view_authenticated(mock_current_user, mock_storage_service):
    # Mock get_current_user dependency
    app.dependency_overrides[get_current_user] = lambda: mock_current_user
    
    response = client.get("/dashboard")
    
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "doc1.pdf" in response.text
    assert "testuser" in response.text
    
    # Clean up overrides
    app.dependency_overrides = {}
