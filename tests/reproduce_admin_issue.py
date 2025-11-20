import pytest
from unittest.mock import MagicMock, AsyncMock
from app.main import root
from app.models.users import User

@pytest.mark.asyncio
async def test_root_redirects_admin_to_admin_dashboard():
    """
    Test that root route redirects admin users to /admin
    """
    # Mock Request with admin session
    mock_request = MagicMock()
    mock_request.session.get.return_value = 1  # user_id

    # Mock DB and User
    mock_db = AsyncMock()
    
    # Mock async generator for get_db
    mock_db_gen = MagicMock()
    mock_db_gen.__anext__.return_value = mock_db
    # Make __anext__ return a future/awaitable
    async def async_next():
        return mock_db
    mock_db_gen.__anext__.side_effect = async_next
    
    mock_db_gen.aclose = AsyncMock()

    # Mock get_db to return our mock
    with pytest.MonkeyPatch.context() as m:
        m.setattr("app.db.get_db", lambda: mock_db_gen)
        
        # Mock get_current_user to return admin user
        admin_user = User(id=1, username="admin", is_admin=True)
        async def mock_get_current_user(req, db):
            return admin_user
            
        m.setattr("app.routers.auth.get_current_user", mock_get_current_user)
        
        # Call root
        response = await root(mock_request)
        
        # Should be a redirect to /admin, NOT a TemplateResponse (dashboard)
        # Currently it returns dashboard (TemplateResponse), so this test should fail or we can assert the failure
        
        # If it was working correctly:
        # assert isinstance(response, RedirectResponse)
        # assert response.headers["location"] == "/admin"
        
        # Current behavior (bug):
        # It calls dashboard() which returns TemplateResponse
        from fastapi.templating import Jinja2Templates
        from starlette.templating import _TemplateResponse
        
        # Expect redirect to /admin
        assert response.status_code == 302
        assert response.headers["location"] == "/admin"
