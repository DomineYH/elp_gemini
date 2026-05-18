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
    # 실패 시 라벨도 이전 텍스트로 되돌려야 한다.
    assert "label.textContent = previousLabelText" in src


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


def test_label_updates_optimistically_before_fetch():
    """체크박스 change 시 라벨은 fetch 응답 전에 즉시 갱신되어야 한다.

    근거: 백엔드 alias_map.replace()는 클라우드 업로드 폴링(최대 60초)으로
    느릴 수 있으므로, UI 라벨은 optimistic 업데이트 후 실패 시 롤백한다.
    """
    src = JS_SOURCE.read_text()

    fetch_index = src.find('await fetch(url')
    assert fetch_index != -1, "fetch 호출이 존재해야 한다"

    # 라벨 즉시 갱신은 fetch 호출보다 먼저 등장해야 한다.
    optimistic_index = src.find("label.textContent = wasChecked ? '활성' : '비활성'")
    assert optimistic_index != -1, "라벨 갱신 라인이 존재해야 한다"
    assert optimistic_index < fetch_index, (
        "라벨 갱신은 fetch 호출보다 먼저 실행되어야 한다 (optimistic update)"
    )
