"""학생 카드·1:1 창 동의 배지가 다짐 동의를 따로 보인다 (#358)."""

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


def _agree_badge_js() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(
        r"function agreeBadge\(ok, pledged\) \{.*?\n    \}", src, re.S
    )
    assert m, "agreeBadge(ok, pledged) 함수를 찾지 못함"
    return m.group(0)


@pytest.mark.parametrize(
    ("ok", "pledged", "cls", "text"),
    [
        (True, True, "agree yes", "✓ 다짐으로 동의"),
        (True, False, "agree yes", "✓ 다음 장면 동의"),
        (False, False, "agree", "대기"),
        (False, True, "agree", "대기"),
    ],
)
def test_agree_badge_text(ok, pledged, cls, text):
    script = (
        "const el = (tag, cls, text) => ({cls, text});\n"
        + _agree_badge_js()
        + f"\nconsole.log(JSON.stringify(agreeBadge({json.dumps(ok)}, "
        + f"{json.dumps(pledged)})));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert json.loads(res.stdout) == {"cls": cls, "text": text}
