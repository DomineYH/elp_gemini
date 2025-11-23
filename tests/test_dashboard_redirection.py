import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_root_redirection_unauthenticated():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"

@pytest.mark.asyncio
async def test_dashboard_access_unauthenticated():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/dashboard", follow_redirects=False)
    assert response.status_code == 401  # Or 302 to login depending on auth middleware

# Note: Testing authenticated state requires mocking the session or auth dependency.
# Since we are using SessionMiddleware, we can try to mock the session in the request.
# However, for a quick verification, checking the unauthenticated redirection and 
# the existence of the endpoint is a good start.

@pytest.mark.asyncio
async def test_dashboard_endpoint_exists():
    """
    Check if /dashboard endpoint is registered and returns 401 for unauthenticated users
    (which confirms it's protected and exists)
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/dashboard")
        # Expecting 401 Unauthorized because of get_current_user dependency
        assert response.status_code == 401
