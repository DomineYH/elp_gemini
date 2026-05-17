"""Static checks for criteria_list.js admin interactions."""

from pathlib import Path

JS_SOURCE = Path("app/static/js/criteria_list.js")


def test_deactivate_action_posts_to_stable_id_endpoint():
    src = JS_SOURCE.read_text()

    assert '.active-checkbox' in src
    assert "/deactivate" in src
    assert "method: 'POST'" in src


def test_escape_cancels_alias_edit_before_blur_commit():
    src = JS_SOURCE.read_text()

    assert "input.dataset.cancelled = 'false'" in src
    assert "input.dataset.cancelled = 'true'" in src
    assert "input.dataset.cancelled === 'true'" in src


def test_failure_reverts_checkbox_state():
    src = JS_SOURCE.read_text()

    assert "cb.checked = previous" in src
    assert "try {" in src
    assert "} catch" in src


def test_replace_action_posts_to_replace_endpoint_with_multipart():
    src = JS_SOURCE.read_text()
    # replace 버튼 셀렉터 바인딩
    assert '[data-action="replace"]' in src
    # FormData multipart 사용
    assert "FormData" in src
    # replace 엔드포인트 경로 문자열이 존재
    assert "/replace" in src
    assert "/api/admin/criteria/" in src
    # 파일 input은 PDF만 (accept 속성)
    assert "application/pdf" in src or ".pdf" in src
