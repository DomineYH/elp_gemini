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
