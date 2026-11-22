"""다시 생성이 또 실패하면 그 행의 횟수가 오른다 (#409).

템플릿의 실제 regenerate()·run()·merge()·bubble()을 꺼내 가짜 api()로 돌린다.
"""

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
let busy = false;
const API = "/api";
const status = {textContent: ""};
const retries = [];
function hideRetry() {}
function showRetry(retry, seconds) { retries.push(seconds); }
function render() {}
function refocus() {}
function shownArtifact() { return ""; }
function el(tag, className, text) {
    return {
        tag, className: className || "", textContent: text ?? "", children: [],
        append(...c) { this.children.push(...c); },
        addEventListener() {},
    };
}
const persona = {id: 3, color_key: "c1"};
const failedRow = {id: 7, seq: 5, persona_id: 3, content: "", structured: null, failed: true};
const okRow = {id: 7, seq: 5, persona_id: 3, content: "네", structured: {action: "", utterance: "네"}};
const state = {utterances: [failedRow], session: {}};
const turn = row => ({utterances: [row], agreement: null, teacher_turns_used: 1});
let answer = null;
async function api() { return answer(); }
function card() {
    const row = state.utterances.find(u => u.id === 7);
    return bubble(persona, row, true).children.map(c => [c.tag, c.textContent]);
}
function fail(retryAfter) {
    return () => {
        const err = new Error("실패");
        if (retryAfter !== undefined) err.retryAfter = retryAfter;
        throw err;
    };
}
"""

_SCENARIO = """
(async () => {
    const out = {};
    out.first = card();
    answer = () => turn(failedRow);
    await regenerate(persona);
    out.once = card();
    await regenerate(persona);
    out.twice = card();
    answer = fail(30);
    await regenerate(persona);
    answer = fail();
    await regenerate(persona);
    out.afterErrors = [card(), regenFails.get(7), retries, status.textContent];
    answer = () => turn(okRow);
    await regenerate(persona);
    out.ok = card();
    console.log(JSON.stringify(out));
})();
"""


def _extract(src: str, pattern: str) -> str:
    m = re.search(pattern, src, re.S)
    assert m, f"템플릿에서 찾지 못함: {pattern}"
    return m.group(0)


def _run_scenario() -> dict:
    src = TEMPLATE.read_text(encoding="utf-8")
    parts = [
        _extract(src, r"const regenFails = new Map\(\);"),
        _extract(src, r"function merge\(turn\) \{.*?\n    \}"),
        _extract(src, r"async function run\(pending, action\) \{.*?\n    \}"),
        _extract(src, r"function bubble\(persona, u, regen\) \{.*?\n    \}"),
        _extract(src, r"function regenerate\(persona\) \{.*?\n    \}"),
    ]
    script = _STUBS + "\n".join(parts) + _SCENARIO
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


def test_regenerate_failing_again_counts_and_success_shows_bubble():
    out = _run_scenario()

    assert out["first"] == [
        ["p", "반응을 읽지 못했습니다."],
        ["button", "다시 생성"],
    ]
    assert out["once"] == [
        ["p", "다시 생성했지만 읽지 못했습니다(1회)."],
        ["button", "다시 생성"],
    ]
    assert out["twice"] == [
        ["p", "다시 생성했지만 읽지 못했습니다(2회)."],
        ["button", "다시 생성"],
    ]
    # 요청 자체가 실패하면(재시도 안내가 있든 없든) 횟수는 그대로다
    card, count, retries, status = out["afterErrors"]
    assert card == out["twice"] and count == 2
    assert retries == [30] and status == "실패"
    assert out["ok"] == [["p", "네"]]
