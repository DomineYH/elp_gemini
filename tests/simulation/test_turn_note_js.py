"""1:1 창 안의 남은 발화·상한 안내와 1:1 '말하기' 버튼의 꺼진 모양 (#408)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path("app/templates/user/simulation.html")
CSS = Path("app/static/css/tailwind.css")
LIMIT = "상한에 도달했습니다. 수업을 종료하고 피드백을 받으세요."

_node = pytest.mark.skipif(shutil.which("node") is None, reason="node 필요")

_STUBS = """
const els = {};
// 안내 줄에 글이 들어가면 대화 영역이 줄어 바닥이 내려간 것과 같다 (#408)
const dmFeed = els.dmFeed = { scrollTop: 0, scrollHeight: 2000 };
let noteText = "";
els.dmTurnNote = {
    get textContent() { return noteText; },
    set textContent(v) { if (v && !noteText) dmFeed.scrollHeight += 19; noteText = v; },
};
const mk = () => ({ textContent: "", disabled: false, className: "", focus() {} });
const $ = id => els[id] ??= mk();
const tInput = $("tInput"), dmInput = $("dmInput");
const dmSubmit = mk();
const dmModal = { querySelector: () => dmSubmit, classList: { add() {}, remove() {} }, contains: () => false };
var document = { activeElement: null, body: null };
function refocus() {}
function syncNextLabels() {}
function syncFinished() {}
let entered = true;
function phaseUtterances() { return entered ? [1] : []; }
let busy = false, dmPersona = null, state = null;
function snap() {
    return {
        turnNote: $("turnNote").textContent, dmTurnNote: $("dmTurnNote").textContent,
        dmInput: dmInput.disabled, dmSubmit: dmSubmit.disabled,
        feedTop: dmFeed.scrollTop, feedHeight: dmFeed.scrollHeight,
    };
}
"""


def _fn(name: str) -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(rf"function {name}\(\) \{{.*?\n    \}}", src, re.S)
    assert m, f"{name} 함수를 찾지 못함"
    return m.group(0)


def _run(status: str, left: int, busy: bool, dm: bool, then: str = "") -> dict:
    state = {
        "session": {
            "status": status,
            "teacher_turns_max": 40,
            "teacher_turns_used": 40 - left,
        },
        "agreement": {"all_agreed": False},
    }
    script = (
        _STUBS
        + _fn("syncControls")
        + "\n"
        + _fn("closeDM")
        + f"\nstate = {json.dumps(state)}; busy = {json.dumps(busy)};"
        + f" dmPersona = {json.dumps({'id': 1} if dm else None)};\n"
        + f"syncControls();\n{then}\nconsole.log(JSON.stringify(snap()));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


@_node
@pytest.mark.parametrize(
    ("status", "left", "busy", "dm", "then", "turn_note", "dm_note"),
    [
        ("running", 6, False, True, "", "", ""),
        ("running", 5, False, False, "", "남은 발화 5회", ""),
        ("running", 5, False, True, "", "", "남은 발화 5회"),
        ("running", 1, False, True, "", "", "남은 발화 1회"),
        ("running", 0, False, True, "", "", LIMIT),
        ("running", 0, False, False, "", LIMIT, ""),
        ("running", 0, False, True, "closeDM();", LIMIT, ""),
        ("running", 3, True, True, "", "", "남은 발화 3회"),
        ("finished", 0, False, True, "", "", ""),
        ("finished", 0, False, False, "", "", ""),
    ],
)
def test_turn_note_goes_to_open_window_only(
    status, left, busy, dm, then, turn_note, dm_note
):
    out = _run(status, left, busy, dm, then)
    assert (out["turnNote"], out["dmTurnNote"]) == (turn_note, dm_note)
    # 두 줄에 함께 글이 들면 스크린 리더가 같은 안내를 두 번 읽는다
    assert not (out["turnNote"] and out["dmTurnNote"])


@_node
def test_limit_with_window_open_disables_dm_input_and_submit():
    out = _run("running", 0, False, True)
    assert out["dmInput"] is True and out["dmSubmit"] is True


@_node
@pytest.mark.parametrize("left", [6, 5, 1, 0])
def test_open_window_feed_stays_at_bottom_after_note(left):
    out = _run("running", left, False, True)
    assert out["feedTop"] == out["feedHeight"]


@_node
@pytest.mark.parametrize(
    ("dm", "then"),
    [(False, ""), (True, "dmFeed.scrollTop = 0; closeDM();")],
    ids=["closed", "closeDM"],
)
def test_closed_window_leaves_feed_scroll_alone(dm, then):
    out = _run("running", 0, False, dm, then)
    assert out["feedTop"] == 0


def _dm_modal() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    start = src.index('<div id="dmModal"')
    return src[start : src.index("<!-- 교사 입력 (하단 고정) -->", start)]


def test_dm_turn_note_is_status_line_before_dm_form():
    modal = _dm_modal()
    m = re.search(r'<p id="dmTurnNote"[^>]*>', modal)
    assert m, "#dmModal 안에 #dmTurnNote가 없음"
    assert 'role="status"' in m.group(0)
    assert m.start() < modal.index('<form id="dmForm"')
    src = TEMPLATE.read_text(encoding="utf-8")
    assert (
        '<p id="turnNote" class="container mx-auto max-w-3xl note mt-1 text-center"'
        ' role="status"></p>' in src
    )


def test_dm_submit_classes_match_tsend():
    src = TEMPLATE.read_text(encoding="utf-8")
    dm = re.search(
        r'<button type="submit" class="([^"]*)">말하기</button>', _dm_modal()
    )
    t = re.search(r'id="tSend" disabled\s+class="([^"]*)"', src)
    assert dm and t
    assert set(dm.group(1).split()) == set(t.group(1).split())
    assert {"disabled:bg-gray-400", "disabled:cursor-not-allowed"} <= set(
        dm.group(1).split()
    )


def test_built_css_has_disabled_rules():
    css = CSS.read_text(encoding="utf-8")
    assert ".disabled\\:bg-gray-400:disabled" in css
    assert ".disabled\\:cursor-not-allowed:disabled" in css


def test_dm_feed_min_height_yields_on_short_viewport():
    m = re.search(r'<div id="dmFeed"[^>]*>', _dm_modal())
    assert m, "#dmFeed가 없음"
    # 고정 12rem이면 낮은 화면(667x375)에서 안내 줄이 더해질 때 입력줄이 잘린다
    assert "min-h-[12rem]" not in m.group(0)
    assert 'style="min-height:min(12rem,25vh)"' in m.group(0)
    assert "flex-1" in m.group(0).split('class="')[1].split('"')[0].split()


def test_dm_turn_note_wraps_between_words():
    m = re.search(r'<p id="dmTurnNote" class="([^"]*)"', _dm_modal())
    assert m and "break-keep" in m.group(1).split()
    assert ".break-keep{word-break:keep-all}" in CSS.read_text(encoding="utf-8")
