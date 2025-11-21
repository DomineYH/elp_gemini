import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.main import app
from app.models.users import User
from app.models.documents import Document
from app.routers.auth import get_current_user
from app.db import get_db

# Mock User
@pytest.fixture
def mock_user():
    return User(id=1, username="testuser", nickname="Test User", email="test@example.com")

# Mock DB Session
@pytest.fixture
def mock_db_session():
    session = AsyncMock(spec=AsyncSession)
    return session

from app.routers.user_docs import dashboard

@pytest.mark.asyncio
async def test_dashboard_renders_upload_when_no_ready_doc(
    mock_db_session, mock_user
):
    """
    Test that dashboard renders upload.html when no ready document exists
    """
    # Mock DB to return no documents
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db_session.execute.return_value = mock_result

    # Mock Request
    mock_request = MagicMock()

    # Call dashboard directly
    response = await dashboard(mock_request, mock_user, mock_db_session)
    
    # Verify template
    assert response.template.name == "user/upload.html"
    assert "user" in response.context

@pytest.mark.asyncio
async def test_dashboard_renders_viewer_when_ready_doc_exists(
    mock_db_session, mock_user
):
    """
    Test that dashboard renders viewer.html when a ready document exists
    """
    # Mock DB to return a ready document
    ready_doc = Document(
        id=1,
        user_id=mock_user.id,
        title="Ready Doc",
        status="ready",
        file_path="/path/to/doc.pdf"
    )
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [ready_doc]
    mock_db_session.execute.return_value = mock_result

    # Mock Request
    mock_request = MagicMock()

    # Call dashboard directly
    response = await dashboard(mock_request, mock_user, mock_db_session)
    
    # Verify template
    assert response.template.name == "user/viewer.html"
    assert response.context["document"] == ready_doc
