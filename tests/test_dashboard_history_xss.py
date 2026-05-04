"""Regression coverage for stored chat history rendering safety."""
import shutil
import subprocess
from pathlib import Path

import pytest

DASHBOARD_TEMPLATE = Path("app/templates/user/dashboard.html")


def _dashboard_source() -> str:
    return DASHBOARD_TEMPLATE.read_text(encoding="utf-8")


def _extract_js_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    brace_start = source.index("{", start)
    depth = 0
    for index in range(brace_start, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"Could not extract JavaScript function: {name}")


def _run_node_script(script: str):
    if shutil.which("node") is None:
        pytest.skip("Node.js runtime is unavailable")

    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


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


def test_dashboard_history_attribute_contexts_use_attribute_escape():
    source = _dashboard_source()

    assert 'title="${escapeHtmlAttribute(title)}"' in source
    assert 'title="${escapeHtmlAttribute(filename)}"' in source
    assert 'title="${escapeHtmlAttribute(lessonName)}"' in source
    assert 'href="${escapeHtmlAttribute(reportUrl)}"' in source
    assert 'title="${escapeHtml(title)}"' not in source
    assert 'title="${escapeHtml(filename)}"' not in source
    assert 'title="${escapeHtml(lessonName)}"' not in source


def test_safe_markdown_url_policy_rejects_executable_protocols():
    source = _dashboard_source()
    function_source = _extract_js_function(source, "isSafeMarkdownUrl")

    _run_node_script(f"""
        const assert = require('node:assert/strict');
        global.window = {{ location: {{ origin: 'https://example.test' }} }};
        {function_source}

        assert.equal(isSafeMarkdownUrl('javascript:alert(1)'), false);
        assert.equal(isSafeMarkdownUrl('java\\nscript:alert(1)'), false);
        const dataUrl = 'data:text/html,<svg onload=alert(1)>';
        assert.equal(isSafeMarkdownUrl(dataUrl), false);
        assert.equal(isSafeMarkdownUrl('https://example.test/report'), true);
        assert.equal(isSafeMarkdownUrl('/api/qna/sessions'), true);
        assert.equal(isSafeMarkdownUrl('mailto:teacher@example.test'), true);
    """)


def test_escape_html_helper_encodes_raw_html_payloads():
    source = _dashboard_source()
    function_source = _extract_js_function(source, "escapeHtml")

    _run_node_script(f"""
        const assert = require('node:assert/strict');
        function encodeHtml(value) {{
            return String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        }}
        global.document = {{
            createElement(tag) {{
                assert.equal(tag, 'div');
                return {{
                    _textContent: '',
                    innerHTML: '',
                    set textContent(value) {{
                        this._textContent = String(value);
                        this.innerHTML = encodeHtml(value);
                    }},
                    get textContent() {{
                        return this._textContent;
                    }},
                }};
            }},
        }};
        {function_source}

        const payload = '<img src=x onerror=alert(1)><script>alert(2)</script>';
        const escaped = escapeHtml(payload);
        assert.equal(escaped.includes('<img'), false);
        assert.equal(escaped.includes('<script>'), false);
        assert.match(escaped, /&lt;img/);
        assert.match(escaped, /&lt;script&gt;/);
        assert.equal(escapeHtml(null), '');
        assert.equal(escapeHtml(undefined), '');
    """)


def test_escape_html_attribute_helper_blocks_quote_breakout_payloads():
    source = _dashboard_source()
    function_source = _extract_js_function(source, "escapeHtmlAttribute")

    _run_node_script(f"""
        const assert = require('node:assert/strict');
        {function_source}

        const payload = '" onmouseover="alert(1)\\' autofocus=\\'x';
        const escaped = escapeHtmlAttribute(payload);

        assert.equal(escaped.includes('"'), false);
        assert.equal(escaped.includes("'"), false);
        assert.equal(escaped.includes('<'), false);
        assert.equal(escaped.includes('>'), false);
        assert.match(escaped, /&quot; onmouseover=&quot;alert\\(1\\)/);
        assert.match(escaped, /&#39; autofocus=&#39;x/);
        assert.equal(escapeHtmlAttribute(null), '');
        assert.equal(escapeHtmlAttribute(undefined), '');
    """)
