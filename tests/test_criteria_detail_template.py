"""criteria_detail template rendering checks without ASGI/TestClient."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATE_DIR = Path("app/templates")


def _criteria(display_alias: str | None):
    return SimpleNamespace(
        id=1,
        title="orig.pdf",
        display_alias=display_alias,
        status="active",
        file_path="/tmp/o.pdf",
        mime_type="application/pdf",
        file_size=1024,
        created_at=datetime(2026, 5, 15, 3, 20, tzinfo=timezone.utc),
        activated_at=None,
        activated_by=None,
        vector_store_id="stores/test",
    )


def _render(criteria) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("admin/criteria_detail.html")
    return template.render(
        user=SimpleNamespace(is_admin=True, email="admin@example.com"),
        criteria=criteria,
    )


def test_detail_shows_display_alias():
    text = _render(_criteria(display_alias="detail-alias"))

    assert "표시명: detail-alias" in text


def test_detail_hides_alias_line_when_null():
    text = _render(_criteria(display_alias=None))

    assert "표시명:" not in text
