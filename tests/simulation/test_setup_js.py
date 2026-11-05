"""최대 인원에서 새 페르소나를 넣으면 누가 빠졌는지 알 수 있다 (#322)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path("app/templates/user/simulation_setup.html")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node 필요"
)


def _pick_into(chosen, ref, max_n):
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(
        r"function pickInto\(chosenArr, ref, max\) \{.*?\n    \}", src, re.S
    )
    assert m, "pickInto 함수를 찾지 못함"
    args = ", ".join(json.dumps(a) for a in (chosen, ref, max_n))
    script = m.group(0) + f"\nconsole.log(JSON.stringify(pickInto({args})));"
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


def test_below_max_adds_without_drop():
    assert _pick_into(["a", "b"], "n", 4) == {
        "chosen": ["a", "b", "n"],
        "dropped": None,
    }


def test_at_max_drops_last_and_adds_new():
    assert _pick_into(["a", "b", "c", "d"], "n", 4) == {
        "chosen": ["a", "b", "c", "n"],
        "dropped": "d",
    }


def test_already_chosen_ref_changes_nothing():
    assert _pick_into(["a", "b", "c", "d"], "c", 4) == {
        "chosen": ["a", "b", "c", "d"],
        "dropped": None,
    }


def test_drop_notice_uses_no_fallback_josa():
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"if \(pickRef\) \{.*?\n            \}", src, re.S)
    assert m and "dropped" in m.group(0)
    assert "(를)" not in m.group(0) and "(을)" not in m.group(0)


# 새 페르소나 저장 후 다시 불러와도 교사가 고른 선택을 유지한다 (#324)


def _run_js(func_pattern, call):
    src = TEMPLATE.read_text(encoding="utf-8")
    funcs = []
    for pat in func_pattern:
        m = re.search(pat, src, re.S)
        assert m, f"함수를 찾지 못함: {pat}"
        funcs.append(m.group(0))
    script = "\n".join(funcs) + f"\nconsole.log(JSON.stringify({call}));"
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


KEEP = r"function keepChosen\(prevArr, candidateRefs\) \{.*?\n    \}"
PICK = r"function pickInto\(chosenArr, ref, max\) \{.*?\n    \}"
REFS = ["a", "b", "c", "d", "e", "f"]


def _keep(prev, refs):
    return _run_js(
        [KEEP], f"keepChosen({json.dumps(prev)}, {json.dumps(refs)})"
    )


def test_keep_chosen_keeps_previous_selection_in_order():
    assert _keep(["a", "c", "e"], REFS) == ["a", "c", "e"]


def test_keep_chosen_drops_refs_missing_from_candidates():
    assert _keep(["a", "x", "e"], REFS) == ["a", "e"]


def test_keep_chosen_empty_when_nothing_remains():
    assert _keep(["x", "y"], REFS) == []


def _keep_then_pick(prev, ref, max_n):
    call = (
        f"pickInto(keepChosen({json.dumps(prev)}, {json.dumps(REFS + [ref])}),"
        f" {json.dumps(ref)}, {max_n})"
    )
    return _run_js([KEEP, PICK], call)


def test_keep_then_pick_below_max_adds_new_ref():
    assert _keep_then_pick(["a", "c", "e"], "n", 4) == {
        "chosen": ["a", "c", "e", "n"],
        "dropped": None,
    }


def test_keep_then_pick_at_max_drops_last_kept_ref():
    assert _keep_then_pick(["a", "c", "e", "f"], "n", 4) == {
        "chosen": ["a", "c", "e", "n"],
        "dropped": "f",
    }


def test_load_keeps_selection_on_pick_ref_reload():
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(
        r"async function load\(newSeed, pickRef\) \{.*?\n    \}", src, re.S
    )
    assert m, "load 함수를 찾지 못함"
    body = m.group(0)
    assert "keepChosen(" in body
    # chooseFirst는 pickRef가 없거나 남은 선택이 없을 때만 부른다
    assert not re.search(r"^ {12}chooseFirst\(", body, re.M)


# 템플릿의 실제 스크립트를 작은 가짜 DOM과 fetch로 돌려 load()를 검증한다 (#324)

_DOM_MOCK = r"""
const els = {};
const docListeners = {};
function fake(tag) {
    return {
        tag, children: [], listeners: {}, dataset: {}, style: {}, value: "", textContent: "",
        addEventListener(t, f) { this.listeners[t] = f; },
        append(...c) { this.children.push(...c); },
        replaceChildren(...c) { this.children = c; },
        setAttribute() {},
    };
}
globalThis.document = {
    getElementById: id => (els[id] ??= fake("div")),
    createElement: tag => fake(tag),
    addEventListener: (t, f) => { docListeners[t] = f; },
};
globalThis.window = {};
let cands = [];
const cand = ref => ({
    ref, pseudonym: ref.toUpperCase(), level: "mid", level_label: "중",
    strong_subjects: [], weak_subjects: [], behavior_summary: "", source: "preset",
});
globalThis.fetch = async () => ({ ok: true, json: async () => ({ seed: 1, candidates: cands.map(cand) }) });
const tick = () => new Promise(r => setTimeout(r, 0));
const toggle = (ref, checked) =>
    els.candRows.listeners.change({ target: { dataset: { ref }, checked } });
const checked = () => els.candRows.children
    .map(tr => tr.children[0].children[0]).filter(b => b.checked).map(b => b.dataset.ref);
const saved = ref => docListeners["sim:persona-saved"]({ detail: { ref } });
"""


def _script_block():
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"<script>\n(\(\(\) => \{.*?\}\)\(\);)\n</script>", src, re.S)
    assert m, "설정 화면 스크립트를 찾지 못함"
    return (
        m.group(1)
        .replace("{{ min_personas }}", "1")
        .replace("{{ max_personas }}", "4")
        .replace("{{ absolute_max }}", "20")
    )


def _run_page(scenario, script=None):
    """초기 후보 a..f, 인원 3명으로 화면을 연 뒤 scenario를 돌린다."""
    js = (
        _DOM_MOCK
        + 'cands = ["a", "b", "c", "d", "e", "f"];\n'
        + 'document.getElementById("count").value = "3";\n'
        + (script or _script_block())
        + "\n(async () => {\nawait tick();\n"
        + scenario
        + "\nconsole.log(JSON.stringify({ checked: checked(),"
        + " status: els.candStatus.textContent }));\n})();"
    )
    res = subprocess.run(
        ["node", "-e", js], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


_MANUAL_ACE = 'toggle("b", false); toggle("e", true);\n'


def test_load_after_save_keeps_manual_selection_and_adds_new():
    out = _run_page(
        _MANUAL_ACE + 'cands = [...cands, "n"]; saved("n"); await tick();'
    )
    assert out == {"checked": ["a", "c", "e", "n"], "status": ""}


def test_load_after_save_at_max_drops_last_kept_and_notifies():
    out = _run_page(
        _MANUAL_ACE
        + 'toggle("f", true); cands = [...cands, "n"]; saved("n"); await tick();'
    )
    assert out == {
        "checked": ["a", "c", "e", "n"],
        "status": "최대 4명 — F 빼고 N 추가",
    }


def test_load_after_save_without_previous_falls_back_to_first_n():
    out = _run_page(
        _MANUAL_ACE
        + 'cands = ["g", "h", "i", "j", "n"]; saved("n"); await tick();'
    )
    # 이전 선택이 모두 사라지면 위에서부터 3명 + 새 페르소나
    assert out["checked"] == ["g", "h", "i", "n"]


def test_reroll_new_seed_picks_first_n():
    out = _run_page(_MANUAL_ACE + "els.reroll.listeners.click(); await tick();")
    assert out == {"checked": ["a", "b", "c"], "status": ""}


def test_page_test_catches_selection_reset_mutation():
    # 리뷰에서 찾은 변이: keepChosen 결과를 버리면 수동 선택이 초기화된다
    script = _script_block()
    good = "const kept = pickRef ? keepChosen([...chosen], candidates.map(c => c.ref)) : [];"
    assert good in script
    bad = script.replace(
        good,
        "const kept = (keepChosen([...chosen], candidates.map(c => c.ref)), []);",
    )
    out = _run_page(
        _MANUAL_ACE + 'cands = [...cands, "n"]; saved("n"); await tick();', bad
    )
    assert out["checked"] == ["a", "b", "c", "n"]
