"""마지막 장면 버튼 문구와 종료된 세션의 하단 안내 (#370)."""

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
const els = {};
const $ = id => els[id] ??= {
    textContent: "", title: "", hidden: new Set(),
    classList: {
        toggle(c, on) { on ? els[id].hidden.add(c) : els[id].hidden.delete(c); },
    },
};
"""


def _fn(name: str) -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(rf"function {name}\(\) \{{.*?\n    \}}", src, re.S)
    assert m, f"{name} 함수를 찾지 못함"
    return m.group(0)


def _run(name: str, idx: int, total: int, status: str, out: str):
    state = {
        "session": {"current_phase_idx": idx, "status": status},
        "phases": [{"idx": i} for i in range(total)],
    }
    script = (
        _STUBS
        + f"const state = {json.dumps(state)};\n"
        + _fn(name)
        + f"\n{name}();\nconsole.log(JSON.stringify({out}));"
    )
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


@pytest.mark.parametrize(
    ("idx", "total", "label", "title"),
    [
        (4, 5, "수업 마치기 →", "학생 동의 없이 수업 마치기"),
        (0, 1, "수업 마치기 →", "학생 동의 없이 수업 마치기"),
        (0, 5, "다음 장면으로 →", "학생 동의 없이 다음 장면으로"),
        (3, 5, "다음 장면으로 →", "학생 동의 없이 다음 장면으로"),
    ],
)
def test_next_labels(idx, total, label, title):
    out = _run(
        "syncNextLabels",
        idx,
        total,
        "running",
        '[$("nextBtn").textContent, $("skipBtn").title]',
    )
    assert out == [label, title]


@pytest.mark.parametrize(
    ("status", "form_hidden", "note_hidden"),
    [("finished", True, False), ("running", False, True)],
)
def test_finished_hides_form_and_shows_note(status, form_hidden, note_hidden):
    out = _run(
        "syncFinished",
        0,
        3,
        status,
        '[$("tForm").hidden.has("hidden"), $("finishedNote").hidden.has("hidden")]',
    )
    assert out == [form_hidden, note_hidden]


def test_finished_note_is_in_fixed_bottom_bar_with_transcript_link():
    src = TEMPLATE.read_text(encoding="utf-8")
    start = src.index("<!-- 교사 입력 (하단 고정) -->")
    bar = src[start : src.index("{% endblock %}", start)]
    m = re.search(
        r'<p id="finishedNote" class="([^"]*)"[^>]*>(.*?)</p>', bar, re.S
    )
    assert m, "하단 고정 영역에 #finishedNote가 없음"
    assert {"hidden", "bg-white"} <= set(m.group(1).split())
    assert "종료된 시뮬레이션입니다." in m.group(2)
    assert re.search(
        r'<a href="/simulation/sessions/\{\{ sid \}\}/transcript"[^>]*>대화록 보기</a>',
        m.group(2),
    )
