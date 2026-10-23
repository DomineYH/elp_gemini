"""상단 교사 말풍선에는 전체 대상 교사 발화만 보인다 (#256)."""

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


def _class_teacher_js() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"function classTeacher\(utts\) \{.*?\n    \}", src, re.S)
    assert m, "classTeacher 함수를 찾지 못함"
    return m.group(0)


def _run(utts):
    script = (
        _class_teacher_js()
        + f"\nconst out = classTeacher({json.dumps(utts)});"
        + "\nconsole.log(JSON.stringify(out ? out.seq : null));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


def _t(seq, target=None):
    return {"seq": seq, "speaker_type": "teacher", "target_persona_id": target}


def _s(seq, pid):
    return {"seq": seq, "speaker_type": "student", "persona_id": pid}


def test_one_to_one_after_class_keeps_class_utterance():
    assert _run([_t(1), _t(2, target=5)]) == 1


def test_returns_last_class_utterance_among_mixed():
    utts = [_t(1), _s(2, 1), _t(3, target=5), _t(4), _s(5, 1), _t(6, target=2)]
    assert _run(utts) == 4


def test_no_teacher_utterance_returns_none():
    assert _run([]) is None
    assert _run([_s(1, 1), _s(2, 2)]) is None
