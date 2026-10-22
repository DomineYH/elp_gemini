"""Shared safe-markdown renderer: one script, tag allowlist, pinned marked."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SAFE_MARKDOWN_JS = Path("app/static/js/safe_markdown.js")
TEMPLATES = [
    Path("app/templates/user/dashboard.html"),
    Path("app/templates/user/report_viewer.html"),
    Path("app/templates/admin/admin_report_viewer.html"),
]


def _allowed_tags() -> set[str]:
    source = SAFE_MARKDOWN_JS.read_text(encoding="utf-8")
    match = re.search(
        r"SAFE_MARKDOWN_TAGS = new Set\(\[(.*?)\]\)", source, re.S
    )
    assert match, "SAFE_MARKDOWN_TAGS allowlist not found"
    return set(re.findall(r"'([a-z0-9]+)'", match.group(1)))


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_templates_load_shared_renderer(template):
    source = template.read_text(encoding="utf-8")

    assert '<script src="/static/js/safe_markdown.js"></script>' in source
    assert "function renderSafeMarkdown(" not in source
    assert "function sanitizeRenderedMarkdown(" not in source


def test_allowlist_keeps_markdown_tags_and_drops_active_content():
    tags = _allowed_tags()

    assert {"blockquote", "br", "p", "a", "img", "input"} <= tags
    for dangerous in (
        "script",
        "iframe",
        "object",
        "embed",
        "svg",
        "math",
        "form",
        "style",
        "link",
        "meta",
        "base",
    ):
        assert dangerous not in tags


def test_sanitizer_removes_disallowed_tags_and_limits_inputs():
    source = SAFE_MARKDOWN_JS.read_text(encoding="utf-8")

    assert "SAFE_MARKDOWN_TAGS.has(" in source
    assert "element.remove()" in source
    assert "'checkbox'" in source


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_templates_pin_marked_version(template):
    source = template.read_text(encoding="utf-8")

    assert re.search(r"cdn\.jsdelivr\.net/npm/marked@\d+\.\d+\.\d+/", source)
    assert "npm/marked/marked.min.js" not in source


def _cjk_strong_extension_js() -> str:
    source = SAFE_MARKDOWN_JS.read_text(encoding="utf-8")
    m = re.search(r"const CJK_STRONG_EXTENSION = \{.*?\n\};", source, re.S)
    assert m, "CJK_STRONG_EXTENSION not found"
    return m.group(0)


def _tokenize(src: str):
    script = (
        _cjk_strong_extension_js()
        + "\nconst lexer = { inlineTokens: s => [{ type: 'text', raw: s }] };"
        + "\nconst token = CJK_STRONG_EXTENSION.tokenizer.call("
        + f"{{ lexer }}, {json.dumps(src)});"
        + "\nconsole.log(JSON.stringify(token || null));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


node_only = pytest.mark.skipif(shutil.which("node") is None, reason="node 필요")


def test_cjk_strong_extension_registered_once():
    source = SAFE_MARKDOWN_JS.read_text(encoding="utf-8")

    assert source.count("marked.use(") == 1
    assert "marked.use({ extensions: [CJK_STRONG_EXTENSION] })" in source


@node_only
@pytest.mark.parametrize(
    ("src", "inner"),
    [
        ("**[5. 평가 계획]**을 보면", "[5. 평가 계획]"),
        ("**‘관찰’**로만", "‘관찰’"),
        ("**「제목」**은", "「제목」"),
        ("**강조**를", "강조"),
        ("**굵게 *기울임* 포함**이다", "굵게 *기울임* 포함"),
        ("**`npm install`**을", "`npm install`"),
    ],
)
def test_cjk_strong_tokenizes_bold_followed_by_josa(src, inner):
    token = _tokenize(src)

    assert token["type"] == "strong"
    assert token["raw"] == f"**{inner}**"
    assert token["text"] == inner
    # Nested inline markup (e.g. *기울임*) is left to marked's lexer.
    assert token["tokens"] == [{"type": "text", "raw": inner}]


@node_only
@pytest.mark.parametrize(
    "src",
    [
        "`**코드**을`",
        "```\n**코드**을\n```",
        "** b ** c",
        "**\n줄바꿈**을",
        "__밑줄__",
        "**x `y**` z",
    ],
)
def test_cjk_strong_leaves_other_markup_alone(src):
    assert _tokenize(src) is None


@node_only
def test_cjk_strong_start_points_at_first_double_star():
    script = (
        _cjk_strong_extension_js()
        + "\nconsole.log(JSON.stringify(["
        + "CJK_STRONG_EXTENSION.start('현재 **x**'),"
        + "CJK_STRONG_EXTENSION.start('없음')]));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert json.loads(res.stdout) == [3, -1]
