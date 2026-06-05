"""App version footer: _app_version() helper and base.html rendering."""

import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


# ------------------------------------------------------------------ 1 & 2
def test_app_version_happy_path_format():
    """_app_version() returns a string like 'v2.323'."""
    from app.templating import _app_version

    result = _app_version()
    assert re.match(r"^v2\.\d+$", result), f"unexpected format: {result!r}"


def test_app_version_fallback_on_subprocess_failure():
    """When git is unavailable, _app_version() returns 'v2'."""
    with patch("app.templating.subprocess.run", side_effect=OSError("no git")):
        from app.templating import _app_version

        assert _app_version() == "v2"


# ------------------------------------------------------------------ 3
def test_app_version_global_registered():
    """Jinja globals dict should contain 'app_version' starting with 'v2'."""
    from app.templating import templates

    assert "app_version" in templates.env.globals
    assert templates.env.globals["app_version"].startswith("v2")


# ------------------------------------------------------------------ 4
def test_footer_renders_version():
    """base.html footer should include the version next to copyright."""
    from app.templating import templates

    tpl = templates.env.get_template("base.html")
    html = tpl.render(
        request=SimpleNamespace(
            session={"user_id": None, "is_admin": False, "nickname": ""},
        ),
    )

    assert "All rights reserved." in html
    assert "·" in html
    # app_version global is already in the env, so 'v2' must appear
    assert re.search(r"v2\.\d+", html)


@pytest.mark.asyncio
async def test_login_page_footer_renders_version():
    """GET /login should render base.html with the app version."""
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/login", follow_redirects=False)

    assert response.status_code == 200
    assert "All rights reserved." in response.text
    assert re.search(r"v2\.\d+", response.text)
