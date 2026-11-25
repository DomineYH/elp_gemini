"""관리자 QnA 로그 세션 필드 이스케이프 회귀 테스트 (#167)."""

import re
from pathlib import Path

TEMPLATE = Path("app/templates/admin/admin_qna_logs.html")

# session_id는 DB 정수, messages.map 안의 본문은 escapeHtml로 따로 감싼다.
ALLOWED_PREFIXES = (
    "escapeHtml(",
    "formatDate(",
    "getUserTypeBadgeClass(",
    "session.message_count",
    "session.session_id",
    "session.messages.map(",
)


def _source() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_session_title_is_escaped():
    src = _source()
    assert "${escapeHtml(session.title || '제목 없음')}" in src
    assert "${session.title || '제목 없음'}" not in src


def test_no_raw_session_interpolation_in_inner_html():
    exprs = re.findall(r"\$\{\s*([^}]*session\.[^}]*)\}", _source())
    raw = [e for e in exprs if not e.strip().startswith(ALLOWED_PREFIXES)]
    assert raw == []


def test_role_badge_is_single_line_pill():
    """'사용자' 3자가 32px 원 안에서 줄바꿈되지 않게 알약 모양으로 그린다 (#448)."""
    src = _source()
    assert "w-8 h-8 rounded-full" not in src
    assert (
        '<span class="inline-flex items-center justify-center h-8 px-2 '
        "text-xs font-medium whitespace-nowrap rounded-full ${"
    ) in src


def test_assistant_bubble_text_is_left_aligned():
    """말풍선은 오른쪽에 두되 본문·시각은 text-right를 물려받지 않는다 (#448)."""
    src = _source()
    assert '<div class="inline-block max-w-[80%] text-left ${' in src
    # 말풍선을 오른쪽에 붙이는 바깥 상자는 그대로다
    assert "${msg.role === 'user' ? 'text-left' : 'text-right'}" in src


def test_qna_log_classes_exist_in_built_css():
    css = Path("app/static/css/tailwind.css").read_text(encoding="utf-8")
    for cls in (
        "h-8",
        "px-2",
        "text-xs",
        "font-medium",
        "whitespace-nowrap",
        "text-left",
    ):
        assert f".{cls}{{" in css, cls
