"""행동만 있는 반응은 말풍선에 한 번만 보인다 (#392)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path("app/templates/user/simulation.html")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node 필요"
)

_STUBS = """
const busy = false;
function regenerate() {}
const state = {utterances: []};
function shownArtifact() { return ""; }
function el(tag, className, text) {
    return {
        tag, className: className || "", textContent: text ?? "", children: [],
        append(...c) { this.children.push(...c); },
        addEventListener() {},
    };
}
"""


def _bubble(u: dict, regen=None):
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(
        r"function bubble\(persona, u, regen\) \{.*?\n    \}", src, re.S
    )
    assert m, "bubble 함수를 찾지 못함"
    script = (
        _STUBS
        + m.group(0)
        + f"\nconst box = bubble({{color_key: 'c1'}}, {json.dumps(u)}, {json.dumps(regen)});"
        + "\nconsole.log(JSON.stringify(box.children.map("
        + "c => [c.tag, c.className, c.textContent])));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return [tuple(c) for c in json.loads(res.stdout)]


@pytest.mark.parametrize(
    ("action", "utterance", "content", "expected"),
    [
        ("A", "", "(A)", [("p", "note mb-0.5", "A")]),
        ("A", "U", "U", [("p", "note mb-0.5", "A"), ("p", "", "U")]),
        ("", "U", "U", [("p", "", "U")]),
        ("", "", "()", [("p", "", "()")]),
    ],
)
def test_bubble_lines(action, utterance, content, expected):
    u = {
        "content": content,
        "structured": {"action": action, "utterance": utterance},
    }
    assert _bubble(u) == expected


def test_bubble_failed_shows_note_and_regen_button():
    out = _bubble({"content": "원문", "failed": True}, regen=True)
    assert out == [
        ("p", "note", "반응을 읽지 못했습니다."),
        (
            "button",
            "mt-1 text-xs px-2 py-1 rounded border bg-white text-gray-700 hover:bg-gray-50",
            "다시 생성",
        ),
    ]
