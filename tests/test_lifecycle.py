import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.main import app
from app.models.users import User
from app.models.documents import Document
from app.routers.auth import get_current_user
from app.db import get_db

# Mock FileSearchService
@pytest.fixture
def mock_fs_service():
    with patch("app.routers.user_docs.FileSearchService") as mock:
        service_instance = mock.return_value
        service_instance.upload_document = AsyncMock(return_value={
            "document_id": "test_doc_id",
            "store_id": "test_store_id"
        })
        service_instance.delete_document = AsyncMock()
        yield service_instance

# Mock DB and User
@pytest.fixture
def mock_db_session():
    session = AsyncMock(spec=AsyncSession)
    return session

@pytest.fixture
def mock_user():
    return User(id=1, username="testuser", nickname="Test User")

@pytest.mark.asyncio
async def test_upload_enforces_single_document_policy(
    mock_fs_service, mock_db_session, mock_user
):
    """
    Test that uploading a new document deletes existing active documents
    """
    # Setup existing document
    existing_doc = Document(
        id=1,
        user_id=mock_user.id,
        title="Old Doc",
        status="ready",
        file_search_file_id="old_fs_id"
    )
    
    # Mock DB execute result
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [existing_doc]
    mock_db_session.execute.return_value = mock_result

    # Override dependencies
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db_session

    client = TestClient(app)

    # Perform upload
    with open("tests/test_files/dummy.pdf", "wb") as f:
        f.write(b"%PDF-1.4 dummy content")

    with open("tests/test_files/dummy.pdf", "rb") as f:
        response = client.post(
            "/docs/upload",
            data={"title": "New Doc"},
            files={"file": ("dummy.pdf", f, "application/pdf")}
        )

    # Verify existing doc was cleaned up
    # 1. Verify delete_document was called for old_fs_id
    mock_fs_service.delete_document.assert_called_with("old_fs_id")
    
    # 2. Verify status was updated to deleted
    assert existing_doc.status == "deleted"

@pytest.mark.asyncio
async def test_session_cleanup(
    mock_fs_service, mock_db_session, mock_user
):
    """
    Test that cleanup endpoint deletes active documents
    """
    # Setup active document
    active_doc = Document(
        id=2,
        user_id=mock_user.id,
        title="Active Doc",
        status="ready",
        file_search_file_id="active_fs_id"
    )

    # Mock DB execute result
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [active_doc]
    mock_db_session.execute.return_value = mock_result

    # Override dependencies
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db_session

    client = TestClient(app)

    # Call cleanup
    response = client.post("/docs/cleanup")

    assert response.status_code == 200
    assert response.json()["message"] == "세션 데이터가 정리되었습니다"

    # Verify cleanup
    mock_fs_service.delete_document.assert_called_with("active_fs_id")
    assert active_doc.status == "deleted"
