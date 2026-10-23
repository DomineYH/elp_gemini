"""#268: 모든 관리자 페이지는 같은 nav 부분 템플릿을 사용한다."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_admin
from app.main import app
from app.models.users import User

client = TestClient(app)

ADMIN_TEMPLATES = Path(__file__).resolve().parents[1] / "app/templates/admin"
NAV_HREFS = [
    "/admin/dashboard",
    "/admin/criteria",
    "/admin/users",
    "/admin/qna-logs",
    "/admin/prompts",
    "/admin/simulation/settings",
    "/admin/simulation/logs",
    "/admin/account",
]
INCLUDE = '{% include "admin/_nav.html" %}'


@pytest.mark.parametrize(
    "path",
    sorted(
        p
        for p in ADMIN_TEMPLATES.glob("*.html")
        if p.name not in ("eval_templates.html", "_nav.html")
    ),
    ids=lambda p: p.name,
)
def test_admin_template_uses_nav_partial(path):
    source = path.read_text(encoding="utf-8")
    assert INCLUDE in source or "block nav_links" not in source


def _get(url):
    admin = User(id=1, username="admin", nickname="Admin", is_admin=True)
    app.dependency_overrides[get_current_admin] = lambda: admin
    try:
        response = client.get(url)
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
    assert response.status_code == 200
    return response.text


def _active_hrefs(body):
    return re.findall(
        r'<a href="([^"]+)" class="text-blue-600 font-medium">', body
    )


@pytest.mark.parametrize(
    "url, active",
    [
        ("/admin/prompts", "/admin/prompts"),
        ("/admin/criteria/upload", "/admin/criteria"),
        ("/admin/simulation/logs", "/admin/simulation/logs"),
    ],
)
def test_admin_page_renders_all_links_with_one_active(url, active):
    body = _get(url)
    for href in NAV_HREFS:
        assert f'<a href="{href}"' in body
    assert _active_hrefs(body) == [active]
