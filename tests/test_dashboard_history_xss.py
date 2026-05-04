"""Regression coverage for stored chat history rendering safety."""
from pathlib import Path

DASHBOARD_TEMPLATE = Path("app/templates/user/dashboard.html")


def _dashboard_source() -> str:
    return DASHBOARD_TEMPLATE.read_text(encoding="utf-8")


def test_past_session_assistant_messages_use_safe_markdown_renderer():
    source = _dashboard_source()

    assert "renderSafeMarkdown(message.content)" in source
    assert "marked.parse(message.content" not in source


def test_safe_markdown_renderer_escapes_html_before_marked_parse():
    source = _dashboard_source()

    assert "const safeInput = escapeHtml(markdown || '');" in source
    assert "const rendered = marked.parse(safeInput);" in source
    assert "return sanitizeRenderedMarkdown(rendered);" in source


def test_safe_markdown_renderer_blocks_unsafe_markdown_urls():
    source = _dashboard_source()

    assert "function isSafeMarkdownUrl(rawUrl)" in source
    assert "['http:', 'https:', 'mailto:', 'tel:']" in source
    assert "link.removeAttribute('href');" in source
    assert "image.replaceWith(" in source
