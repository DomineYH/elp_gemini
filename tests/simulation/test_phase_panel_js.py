"""장면 패널: 승계 초안 출처 표시와 지도안에서 다시 나누기 (#342).

템플릿의 실제 스크립트를 작은 가짜 DOM과 fetch로 node에서 돌린다 (test_setup_js.py 방식).
"""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

TEMPLATE = Path("app/templates/user/_sim_phase_panel.html")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node 필요"
)

ROW = {
    "name": "도입",
    "minutes": 10,
    "teacher_prompt": "발문",
    "task": "과업",
    "materials": "자료",
    "cautions": "유의점",
    "source_span": "원문 발췌",
}
REGEN = [
    {**ROW, "name": f"새 장면{i}", "teacher_prompt": f"새 발문{i}"}
    for i in (1, 2, 3)
]
FALLBACK = [
    {
        "name": n,
        "minutes": None,
        "teacher_prompt": "",
        "task": "",
        "materials": "",
        "cautions": "",
        "source_span": "",
    }
    for n in ("도입", "활동1", "정리")
]
INHERITED_TITLE = "장면 1개 · 이전 시뮬레이션에서 가져옴 · 수정"
FAIL_NOTICE = (
    "지도안에서 장면을 다시 나누지 못했습니다. 기존 장면을 그대로 둡니다."
)

_DOM_MOCK = r"""
const els = {};
let focused = null;
function fake(tag) {
    return {
        tag, children: [], listeners: {}, value: "", textContent: "", open: false,
        addEventListener(t, f) { this.listeners[t] = f; },
        append(...c) { this.children.push(...c); },
        replaceChildren(...c) { this.children = c; },
        setAttribute() {},
        focus() { focused = this.id; },
    };
}
globalThis.document = {
    // 템플릿 마크업에 있는 id만 요소가 있다 (없는 id는 브라우저처럼 null)
    getElementById: id => IDS.includes(id) ? (els[id] ??= Object.assign(fake("div"), { id })) : null,
    createElement: fake,
};
globalThis.window = {};
const calls = [];
let release = null;
globalThis.fetch = async url => {
    calls.push(url);
    const r = RESPONSES.shift();
    if (r === "pending") return new Promise(res => { release = res; });
    return { ok: r.ok, status: r.ok ? 200 : 500, json: async () => r.body };
};
globalThis.confirm = () => CONFIRM;
const tick = () => new Promise(r => setTimeout(r, 0));
const regen = () => document.getElementById("phaseRegen").listeners.click();
function readOut() {
    try { return { phases: window.simPhasePanel.read() }; }
    catch (e) { return { error: e.message }; }
}
"""


class _Markup(HTMLParser):
    """id가 있는 요소마다 태그, 속성, 조상 태그를 모은다."""

    def __init__(self):
        super().__init__()
        self.stack, self.elements = [], {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.elements[attrs["id"]] = (tag, attrs, list(self.stack))
        self.stack.append(tag)

    def handle_endtag(self, tag):
        while self.stack and self.stack.pop() != tag:
            pass


def _elements():
    parser = _Markup()
    parser.feed(TEMPLATE.read_text(encoding="utf-8"))
    return parser.elements


def _script():
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"<script>\n(.*?)</script>", src, re.S)
    assert m, "패널 스크립트를 찾지 못함"
    return m.group(1)


def _run(responses, scenario="", confirm=True, script=None):
    """responses[0]은 첫 초안 응답, 이후는 다시 나누기 응답 ("pending"이면 보류)."""
    js = (
        f"const RESPONSES = {json.dumps(responses, ensure_ascii=False)};\n"
        f"const CONFIRM = {json.dumps(confirm)};\n"
        f"const IDS = {json.dumps(list(_elements()))};\n"
        + _DOM_MOCK
        + (script or _script())
        + "\n(async () => {\nawait tick();\n"
        + scenario
        + '\nconst b = document.getElementById("phaseRegen");'
        + "\nconsole.log(JSON.stringify({ ...readOut(), calls, focused,"
        + ' summary: document.getElementById("phaseSummary").textContent,'
        + ' notice: document.getElementById("phaseNotice").textContent,'
        + ' open: document.getElementById("phasePanel").open,'
        + " hidden: b.hidden, disabled: b.disabled,"
        + " label: b.textContent }));\n})();"
    )
    res = subprocess.run(
        ["node", "-e", js], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


def _draft(source, phases=None, notice=None):
    return {
        "ok": True,
        "body": {"source": source, "phases": phases or [ROW], "notice": notice},
    }


_EDIT_NAME = (
    "const nameInput = els.phaseRows.children[0].children[0].children[1];\n"
    'nameInput.value = "고친 도입"; nameInput.listeners.input();\n'
)


def test_inherited_shows_origin_and_regen_button():
    out = _run([_draft("inherited")])
    assert out["summary"] == INHERITED_TITLE
    assert out["hidden"] is False
    assert out["open"] is False
    assert out["notice"] == (
        "이전 시뮬레이션에서 쓴 장면입니다. "
        "지도안에서 새로 나누려면 '지도안에서 다시 나누기'를 누르세요."
    )


def test_generated_hides_regen_button():
    out = _run([_draft("generated")])
    assert out["summary"] == "장면 1개 감지 · 수정"
    assert out["hidden"] is True
    assert out["notice"] == ""


def test_fallback_hides_regen_button():
    out = _run([_draft("fallback", FALLBACK, notice="서버 안내")])
    assert out["summary"] == "장면 3개 감지 · 수정"
    assert out["hidden"] is True
    assert out["open"] is True
    assert out["notice"] == "서버 안내"


def test_read_keeps_readonly_fields():
    out = _run([_draft("inherited")])
    assert out["phases"] == [ROW]


def test_regen_cancel_does_nothing():
    out = _run([_draft("inherited")], "regen(); await tick();", confirm=False)
    assert out["calls"] == ["/api/simulation/phases/draft"]
    assert out["phases"] == [ROW]
    assert out["summary"] == INHERITED_TITLE


def test_regen_success_replaces_rows():
    out = _run(
        [_draft("inherited"), _draft("generated", REGEN)],
        "await regen(); await tick();",
    )
    assert len(out["calls"]) == 2
    assert "fresh=1" in out["calls"][1]
    assert [p["name"] for p in out["phases"]] == [
        "새 장면1",
        "새 장면2",
        "새 장면3",
    ]
    assert out["summary"] == "장면 3개 감지 · 수정"
    assert out["hidden"] is True
    assert out["open"] is True
    assert out["notice"] == (
        "지도안에서 장면을 다시 나눴습니다. 이전 장면으로 돌아가려면 새로고침하세요."
    )
    assert out["focused"] == "phaseSummary"


def _assert_kept_edited(out):
    assert out["phases"] == [{**ROW, "name": "고친 도입"}]
    assert out["summary"] == INHERITED_TITLE
    assert out["notice"] == FAIL_NOTICE
    assert out["hidden"] is False
    assert out["disabled"] is False
    assert out["label"] == "지도안에서 다시 나누기"


def test_regen_fallback_keeps_edited_rows():
    out = _run(
        [_draft("inherited"), _draft("fallback", FALLBACK, notice="서버 안내")],
        _EDIT_NAME + "await regen(); await tick();",
    )
    _assert_kept_edited(out)


def test_regen_http_error_keeps_rows():
    out = _run(
        [_draft("inherited"), {"ok": False, "body": {"detail": "x"}}],
        _EDIT_NAME + "await regen(); await tick();",
    )
    _assert_kept_edited(out)


def test_regen_busy_blocks_read_and_button():
    out = _run([_draft("inherited"), "pending"], "regen(); await tick();")
    assert out["disabled"] is True
    assert out["label"] == "다시 나누는 중..."
    assert out["notice"] == "지도안에서 장면을 다시 나누는 중..."
    assert "다시 나누는 중" in out["error"]


def test_regen_test_catches_overwrite_mutation():
    # 실패 판정을 HTTP 상태만으로 하면 fallback 빈 행이 교사가 고친 표를 덮어쓴다
    script = _script()
    good = 'if (body.source !== "generated") throw new Error("regen failed");'
    assert good in script
    bad = script.replace(good, 'if (!res.ok) throw new Error("regen failed");')
    out = _run(
        [_draft("inherited"), _draft("fallback", FALLBACK, notice="서버 안내")],
        _EDIT_NAME + "await regen(); await tick();",
        script=bad,
    )
    assert "error" in out  # 빈 발문 행이 들어와 read()가 막힌다
    assert out["summary"] == "장면 3개 감지 · 수정"


def test_markup_structure():
    els = _elements()
    tag, attrs, ancestors = els["phaseRegen"]
    assert tag == "button" and attrs.get("type") == "button"
    assert "hidden" in attrs
    assert (
        "summary" not in ancestors
    )  # 대화형 요소를 <summary> 안에 넣지 않는다
    assert ancestors[-1] == "details"
    assert els["phaseNotice"][1].get("role") == "status"
    assert els["phaseSummary"][0] == "summary"
