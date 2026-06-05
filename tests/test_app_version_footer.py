"""App version footer: _app_version() helper and base.html rendering."""

import re
from types import SimpleNamespace
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader, select_autoescape


# ------------------------------------------------------------------ 1 & 2
def test_app_version_happy_path_format():
    """_app_version() returns a string like 'v2.323'."""
    from app.main import _app_version

    result = _app_version()
    assert re.match(r"^v2\.\d+$", result), f"unexpected format: {result!r}"


def test_app_version_fallback_on_subprocess_failure():
    """When git is unavailable, _app_version() returns 'v2'."""
    with patch("app.main.subprocess.run", side_effect=OSError("no git")):
        from app.main import _app_version

        assert _app_version() == "v2"


# ------------------------------------------------------------------ 3
def test_app_version_global_registered():
    """Jinja globals dict should contain 'app_version' starting with 'v2'."""
    from app.main import templates

    assert "app_version" in templates.env.globals
    assert templates.env.globals["app_version"].startswith("v2")


# ------------------------------------------------------------------ 4
def test_footer_renders_version():
    """base.html footer should include the version next to copyright."""
    from app.main import templates

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
