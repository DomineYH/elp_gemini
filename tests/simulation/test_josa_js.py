"""1:1 대화 안내가 이름 받침에 맞춰 '와/과'를 고른다 (#164)."""

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


def _josa_wa_js() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"function josaWa\(name\) \{.*?\n    \}", src, re.S)
    assert m, "josaWa 함수를 찾지 못함"
    return m.group(0)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("준서", "와"),
        ("도현", "과"),
        ("서연", "과"),
        ("지우", "와"),
        ("", "와"),
        ("Amy", "와"),
    ],
)
def test_josa_wa_by_final_consonant(name, expected):
    script = (
        _josa_wa_js()
        + f"\nconsole.log(JSON.stringify(josaWa({json.dumps(name)})));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert json.loads(res.stdout) == expected


def test_dm_notice_has_no_fallback_josa():
    src = TEMPLATE.read_text(encoding="utf-8")
    assert '"과(와)의' not in src
