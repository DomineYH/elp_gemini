"""교실 보드 좌석에 전체 발화와 학생 반응이 시간순으로 짝지어 보인다 (#176)."""

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


def _seat_utterances_js() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(
        r"function seatUtterances\(utts, p\) \{.*?\n    \}", src, re.S
    )
    assert m, "seatUtterances 함수를 찾지 못함"
    return m.group(0)


def _run(utts, persona_id):
    script = (
        _seat_utterances_js()
        + f"\nconst out = seatUtterances({json.dumps(utts)}, "
        + f"{{id: {persona_id}}});"
        + "\nconsole.log(JSON.stringify(out.map(u => u.seq)));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


def _t(seq, target=None):
    return {"seq": seq, "speaker_type": "teacher", "target_persona_id": target}


def _s(seq, pid):
    return {"seq": seq, "speaker_type": "student", "persona_id": pid}


UTTS = [
    _t(1),
    _s(2, 1),
    _s(3, 2),
    _t(4),
    _s(5, 1),
    _s(6, 2),
    _t(7),
    _s(8, 1),
    _s(9, 2),
    _t(10, target=2),
    _s(11, 2),
    {"seq": 12, "speaker_type": "system", "target_persona_id": None},
]


def test_whole_class_utterances_pair_with_each_seat():
    # 전체 발화 3회 → 좌석마다 교사 발화·반응이 번갈아 시간순
    assert _run(UTTS, 1) == [1, 2, 4, 5, 7, 8]


def test_one_to_one_stays_on_target_seat_only():
    assert _run(UTTS, 2) == [1, 3, 4, 6, 7, 9, 10, 11]
    assert 10 not in _run(UTTS, 1)


def test_dm_marks_whole_class_teacher_bubble():
    src = TEMPLATE.read_text(encoding="utf-8")
    assert '"(전체에게) " + u.content' in src
