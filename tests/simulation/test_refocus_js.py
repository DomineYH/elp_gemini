"""응답이 끝나면 보이는 입력창에 포커스를 돌려준다 (#314)."""

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


def _refocus_js() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"function refocus\(\) \{.*?\n    \}", src, re.S)
    assert m, "refocus 함수를 찾지 못함"
    return m.group(0)


@pytest.mark.parametrize(
    ("active", "dm_open", "t_disabled", "coarse", "expected"),
    [
        ("body", False, False, False, "t"),
        ("body", True, False, False, "dm"),
        ("null", False, False, False, "t"),
        ("{}", False, False, False, None),
        ("body", False, True, False, None),
        ("body", False, False, True, None),
    ],
)
def test_refocus(active, dm_open, t_disabled, coarse, expected):
    stubs = f"""
let focused = null;
const body = {{}};
var document = {{ body, activeElement: {active} }};
var matchMedia = () => ({{ matches: {json.dumps(coarse)} }});
var dmPersona = {json.dumps("p1" if dm_open else None)};
var tInput = {{ disabled: {json.dumps(t_disabled)}, focus() {{ focused = "t"; }} }};
var dmInput = {{ disabled: false, focus() {{ focused = "dm"; }} }};
"""
    script = (
        stubs
        + _refocus_js()
        + "\nrefocus();\nconsole.log(JSON.stringify(focused));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert json.loads(res.stdout) == expected
