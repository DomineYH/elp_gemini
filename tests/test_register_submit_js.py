"""가입 폼은 한 번만 제출되고, bfcache로 돌아오면 다시 제출할 수 있다 (#443)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path("app/templates/user/register.html")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node 필요"
)

STUBS = """
const formListeners = {};
const winListeners = {};
const buttonListeners = {};
const button = {
    disabled: false,
    addEventListener(t, f) { buttonListeners[t] = f; },
};
const form = {
    addEventListener(t, f) { formListeners[t] = f; },
    querySelector: (sel) => (sel === 'button[type="submit"]' ? button : null),
};
var document = {
    querySelector: (sel) => (sel === 'form[action="/auth/register"]' ? form : null),
};
var window = { addEventListener(t, f) { winListeners[t] = f; } };
const log = [];
function submit() {
    let prevented = false;
    formListeners.submit({ preventDefault() { prevented = true; } });
    log.push({ prevented, disabled: button.disabled });
}
function pageshow(persisted) {
    winListeners.pageshow({ persisted });
    log.push({ disabled: button.disabled });
}
"""


def _page_js() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"\{% block scripts %\}\s*<script>(.*?)</script>", src, re.S)
    assert m, "register.html에 scripts 블록 스크립트가 없음"
    return m.group(1)


def _run(steps: str):
    script = (
        STUBS
        + _page_js()
        + "\n"
        + steps
        + "\nconsole.log(JSON.stringify({ log, button: button.disabled,"
        " buttonListeners: Object.keys(buttonListeners) }));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


def test_first_submit_goes_through_and_disables_button():
    out = _run("submit();")
    assert out["log"] == [{"prevented": False, "disabled": True}]


def test_second_submit_is_prevented():
    out = _run("submit(); submit(); submit();")
    assert [e["prevented"] for e in out["log"]] == [False, True, True]


def test_pageshow_from_bfcache_reenables_submit():
    out = _run("submit(); pageshow(true); submit();")
    assert out["log"] == [
        {"prevented": False, "disabled": True},
        {"disabled": False},
        {"prevented": False, "disabled": True},
    ]


def test_pageshow_without_bfcache_keeps_guard():
    out = _run("submit(); pageshow(false); submit();")
    assert out["log"][-1] == {"prevented": True, "disabled": True}


def test_no_submit_event_leaves_button_enabled():
    # 브라우저 검증 실패는 submit 이벤트를 내지 않는다: 클릭만으로는 막히지 않아야 한다
    out = _run("")
    assert out["button"] is False
    assert out["buttonListeners"] == []
