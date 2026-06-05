"""App version footer: _app_version() helper and base.html rendering."""

import os
import re
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


# ------------------------------------------------------------------ 1 & 2
def test_app_version_happy_path_format(monkeypatch):
    """_app_version() returns a string like 'v2.323'."""
    monkeypatch.delenv("APP_VERSION", raising=False)

    from app.templating import _app_version

    result = _app_version()
    assert re.match(r"^v2\.\d+$", result), f"unexpected format: {result!r}"


def test_app_version_env_override(monkeypatch):
    """APP_VERSION overrides git-derived version."""
    monkeypatch.setenv("APP_VERSION", "v9.999")

    from app.templating import _app_version

    assert _app_version() == "v9.999"


def test_app_version_with_restricted_path(monkeypatch, tmp_path):
    """_app_version() finds git even when inherited PATH has no git."""
    monkeypatch.delenv("APP_VERSION", raising=False)

    augmented_path = os.pathsep.join(
        [str(tmp_path), "/usr/bin", "/usr/local/bin", "/bin"]
    )
    if shutil.which("git", path=augmented_path) is None:
        pytest.skip("git is not installed in standard system paths")

    monkeypatch.setenv("PATH", str(tmp_path))

    from app.templating import _app_version

    result = _app_version()
    assert re.match(r"^v2\.\d+$", result), f"unexpected format: {result!r}"


def test_app_version_fallback_on_subprocess_failure(monkeypatch):
    """When git is unavailable, _app_version() returns 'v2'."""
    monkeypatch.delenv("APP_VERSION", raising=False)

    with patch("app.templating.subprocess.run", side_effect=OSError("no git")):
        from app.templating import _app_version

        assert _app_version() == "v2"


# ------------------------------------------------------------------ 3
def test_app_version_global_registered():
    """Jinja globals dict should contain 'app_version' starting with 'v2'."""
    from app.templating import templates

    assert "app_version" in templates.env.globals
    registered_version = templates.env.globals["app_version"]
    configured_version = os.environ.get("APP_VERSION")
    assert registered_version.startswith("v2") or (
        configured_version and registered_version == configured_version
    )


# ------------------------------------------------------------------ 4
def test_footer_renders_version():
    """base.html footer should include the version next to copyright."""
    from app.templating import templates

    registered_version = templates.env.globals["app_version"]
    tpl = templates.env.get_template("base.html")
    html = tpl.render(
        request=SimpleNamespace(
            session={"user_id": None, "is_admin": False, "nickname": ""},
        ),
    )

    assert "All rights reserved." in html
    assert "·" in html
    assert f"· {registered_version}" in html


@pytest.mark.asyncio
async def test_login_page_footer_renders_version():
    """GET /login should render base.html with the app version."""
    from app.main import app
    from app.templating import templates

    registered_version = templates.env.globals["app_version"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/login", follow_redirects=False)

    assert response.status_code == 200
    assert "All rights reserved." in response.text
    assert f"· {registered_version}" in response.text
