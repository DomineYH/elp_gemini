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
const regenFails = new Map([[7, 2]]);
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


def test_bubble_failed_again_shows_regen_count():
    # 다시 생성이 또 실패한 횟수는 이 화면의 regenFails에서 센다 (#409)
    out = _bubble({"id": 7, "content": "", "failed": True}, regen=True)
    assert out[0] == ("p", "note", "다시 생성했지만 읽지 못했습니다(2회).")
    assert out[1][0] == "button" and out[1][2] == "다시 생성"


_DM_STUBS = """
const busy = false;
function regenerate() {}
function shownArtifact() { return ""; }
function node(tag, className, text) {
    return {
        tag, className: className || "", textContent: text ?? "", children: [], style: {},
        classList: {add() {}},
        append(...c) { this.children.push(...c); },
        prepend(...c) { this.children.unshift(...c); },
        replaceChildren(...c) { this.children = c; },
        addEventListener() {},
    };
}
const el = node;
const nodes = {};
const $ = id => (nodes[id] ??= node("div"));
const understandBar = () => node("div"), agreeBadge = () => node("span"), typing = () => node("div");
const josaWa = () => "와", currentPhase = () => ({name: "도입"});
const state = {utterances: [], agreement: {agreed_persona_ids: [], pledged_persona_ids: [], understanding: {}}};
const dmPersona = {id: 1, display_name: "채원", color_key: "c1", adapted_level: "", adapted_profile: {}};
const T = (id, target) => ({id, speaker_type: "teacher", content: "말", target_persona_id: target});
const S = (id, persona, failed) => ({id, speaker_type: "student", persona_id: persona, content: "네", failed});
const UTTS = [T(1, null), S(2, 1, true), S(3, 2, false), T(4, 1), S(5, 1, true), T(6, 2), S(7, 2, true)];
"""


def _render_dm(stubs: str, report: str, utts: str = "UTTS") -> object:
    src = TEMPLATE.read_text(encoding="utf-8")
    parts = [
        re.search(pat, src, re.S).group(0)
        for pat in (
            r"function seatUtterances\(utts, p\) \{.*?\n    \}",
            r"function renderDM\(utts, pending\) \{.*?\n    \}",
        )
    ]
    script = (
        _DM_STUBS
        + stubs
        + "\n".join(parts)
        + f"\nrenderDM({utts}, new Set());\nconsole.log(JSON.stringify("
        + report
        + "));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


def test_dm_regen_only_on_last_student_reaction():
    # 1:1 창도 좌석과 같은 조건으로 "다시 생성"을 붙인다 (#414)
    calls = _render_dm(
        "const calls = [];\n"
        "function bubble(p, u, regen) { calls.push([u.id, !!regen]); return node('div'); }\n",
        "calls",
    )
    assert calls == [[2, False], [5, True]]


def test_dm_failed_again_card_shows_count_and_button():
    # 다시 생성이 또 실패한 행은 창 안에서도 횟수와 버튼을 보인다 (#414, #409)
    src = TEMPLATE.read_text(encoding="utf-8")
    real_bubble = re.search(
        r"function bubble\(persona, u, regen\) \{.*?\n    \}", src, re.S
    ).group(0)
    cards = _render_dm(
        "const regenFails = new Map([[5, 1]]);\n" + real_bubble + "\n",
        "nodes.dmFeed.children.slice(1).map(r => r.children[0])"
        ".filter(b => b.children.length > 1)"
        ".map(b => b.children.slice(1).map(c => [c.tag, c.textContent]))",
    )
    assert cards == [
        [["p", "반응을 읽지 못했습니다."]],
        [
            ["p", "다시 생성했지만 읽지 못했습니다(1회)."],
            ["button", "다시 생성"],
        ],
    ]


def test_dm_no_regen_on_old_failed_row_after_valid_reaction():
    # 실패 행 뒤에 정상 반응이 오면 옛 실패 카드에는 버튼이 없다(서버는 409) (#414)
    calls = _render_dm(
        "const calls = [];\n"
        "function bubble(p, u, regen) { calls.push([u.id, !!regen]); return node('div'); }\n",
        "calls",
        "[T(1, 1), S(2, 1, true), T(3, 1), S(4, 1, false)]",
    )
    assert dict(calls)[2] is False
