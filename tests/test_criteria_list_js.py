"""Static checks for criteria_list.js admin interactions."""

from pathlib import Path


JS_SOURCE = Path("app/static/js/criteria_list.js")


def test_deactivate_action_posts_to_stable_id_endpoint():
    src = JS_SOURCE.read_text()

    assert "data-action=\"deactivate\"" in src
    assert "/deactivate`" in src
    assert "method: 'POST'" in src


def test_escape_cancels_alias_edit_before_blur_commit():
    src = JS_SOURCE.read_text()

    assert "input.dataset.cancelled = 'false'" in src
    assert "input.dataset.cancelled = 'true'" in src
    assert "input.dataset.cancelled === 'true'" in src
