"""criteria_list template rendering checks without ASGI/TestClient."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATE_DIR = Path("app/templates")


def _item(
    *,
    stable_id: str = "01HSTABLE001",
    title: str = "orig.pdf",
    display_alias: str | None = "my-alias",
    status: str = "uploaded",
):
    return SimpleNamespace(
        stable_id=stable_id,
        title=title,
        display_alias=display_alias,
        status=status,
        created_at=datetime(2026, 5, 15, 3, 21, tzinfo=timezone.utc),
    )


def _render(items, sync_state: str = "ok") -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("admin/criteria_list.html")
    return template.render(
        user=SimpleNamespace(is_admin=True, email="admin@example.com"),
        criteria_items=items,
        sync=SimpleNamespace(
            state=sync_state,
            last_synced_at="2026-05-15T03:21:00Z",
            error=None,
        ),
    )


def test_template_renders_empty_state():
    text = _render([])

    assert "평가 기준이 없습니다" in text


def test_template_has_single_table_with_alias_cell_and_active_radio():
    text = _render([_item(status="active")])

    assert 'class="alias-cell' in text
    assert 'class="active-radio' in text
    assert "my-alias" in text
    assert "01HSTABLE001" in text
    assert "활성" in text
    assert "클라우드 Store 문서" not in text
    assert "동기화 확정" not in text
    assert "(매칭 없음)" not in text


def test_template_alias_unset_placeholder():
    text = _render([
        _item(
            stable_id="01HSTABLE002",
            title="no-alias.pdf",
            display_alias=None,
        )
    ])

    assert "(미설정)" in text
    assert "비활성" in text


def test_active_row_has_deactivate_control_with_stable_id():
    text = _render([_item(stable_id="01HACTIVE", status="active")])

    assert 'data-action="deactivate"' in text
    assert 'data-stable-id="01HACTIVE"' in text


def test_uploaded_rows_do_not_render_deactivate_control():
    text = _render([_item(stable_id="01HUPLOADED", status="uploaded")])

    assert 'data-action="deactivate"' not in text
