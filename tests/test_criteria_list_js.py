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
    느릴 수 있으므로, UI 라벨은 optimistic 업데이트('반영중…') 후 응답
    수신 시 최종 텍스트로 확정한다.
    """
    src = JS_SOURCE.read_text()

    fetch_index = src.find('await fetch(url')
    assert fetch_index != -1, "fetch 호출이 존재해야 한다"

    # 시작 시 pending 라벨이 fetch 호출보다 먼저 등장해야 한다.
    pending_assignment = (
        "label.textContent = pendingLabelText"
    )
    pending_index = src.find(pending_assignment)
    assert pending_index != -1, "pending 라벨 할당 라인이 존재해야 한다"
    assert pending_index < fetch_index, (
        "pending 라벨 할당은 fetch 호출보다 먼저 실행되어야 한다 "
        "(optimistic update)"
    )


def test_checkbox_disabled_while_request_in_flight():
    """change 핸들러는 fetch 호출 전에 체크박스를 disable 해야 한다.

    근거: alias_map.replace() 가 수 초~수십 초 걸리는 동안 사용자가 다시
    토글하면 두 번째 요청이 서버 측 alias_map 충돌을 일으켜 503/needs_resync
    가 발생한다. 클라이언트에서 in-flight 잠금으로 첫 단계 차단.
    """
    src = JS_SOURCE.read_text()

    fetch_index = src.find('await fetch(url')
    assert fetch_index != -1
    disable_index = src.find('cb.disabled = true')
    assert disable_index != -1, "체크박스 disable 라인이 존재해야 한다"
    assert disable_index < fetch_index, (
        "cb.disabled = true 는 fetch 호출보다 먼저 실행되어야 한다"
    )


def test_label_shows_pending_while_request_in_flight():
    """change 시작 시 라벨은 '반영중…' 으로 표시되어야 한다.

    근거: optimistic 라벨 갱신은 유지하되, 아직 클라우드에 commit 되지
    않았음을 사용자에게 알린다.
    """
    src = JS_SOURCE.read_text()

    pending_active = "'활성 반영중…'"
    pending_inactive = "'비활성 반영중…'"
    assert pending_active in src, "'활성 반영중…' 라벨이 존재해야 한다"
    assert pending_inactive in src, "'비활성 반영중…' 라벨이 존재해야 한다"


def test_checkbox_re_enabled_after_request_finishes():
    """요청 종료 후 체크박스는 항상 다시 enable 되어야 한다 (try/finally).

    근거: 성공/실패 어느 경로에서도 disabled 상태가 남으면 행이 영구
    잠긴다.
    """
    src = JS_SOURCE.read_text()

    # finally 블록 또는 catch/then 양쪽에서 enable 보장
    assert 'cb.disabled = false' in src, (
        "응답 후 체크박스를 enable 하는 라인이 존재해야 한다"
    )
    # finally 키워드 사용 (가장 안전한 패턴)
    assert '} finally {' in src, (
        "try/finally 패턴으로 disabled 해제를 보장해야 한다"
    )
