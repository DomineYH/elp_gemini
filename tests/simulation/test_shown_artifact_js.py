"""학생 산출물은 같은 장면에서 직전 산출물과 다를 때만 보인다 (#389)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SIM = Path("app/templates/user/simulation.html")
TRANSCRIPT = Path("app/templates/user/simulation_transcript.html")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node 필요"
)


def _fn(path: Path, sig: str) -> str:
    src = path.read_text(encoding="utf-8")
    m = re.search(rf"function {re.escape(sig)} \{{.*?\n    \}}", src, re.S)
    assert m, f"{sig}를 {path}에서 찾지 못함"
    return m.group(0)


def _node(script: str):
    res = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(res.stdout)


def _shown(utts, seq):
    script = (
        _fn(SIM, "shownArtifact(utts, u)")
        + f"\nconst utts = {json.dumps(utts)};"
        + f"\nconst u = utts.find(x => x.seq === {seq});"
        + "\nconsole.log(JSON.stringify(shownArtifact(utts, u)));"
    )
    return _node(script)


def _s(seq, pid, artifact, phase=0):
    return {
        "seq": seq,
        "speaker_type": "student",
        "persona_id": pid,
        "phase_idx": phase,
        "structured": {"artifact": artifact},
    }


def test_first_then_same_then_new():
    utts = [_s(1, 1, "A"), _s(2, 1, "A"), _s(3, 1, "B")]
    assert [_shown(utts, s) for s in (1, 2, 3)] == ["A", "", "B"]


def test_same_after_blank_stays_hidden():
    utts = [_s(1, 1, "A"), _s(2, 1, ""), _s(3, 1, "A")]
    assert _shown(utts, 3) == ""


@pytest.mark.parametrize("artifact", ["", "   ", None])
def test_blank_artifact_hidden(artifact):
    assert _shown([_s(1, 1, artifact)], 1) == ""


def test_new_scene_shows_again():
    utts = [_s(1, 1, "A", phase=0), _s(2, 1, "A", phase=1)]
    assert _shown(utts, 2) == "A"


def test_counted_per_student():
    utts = [_s(1, 1, "A"), _s(2, 2, "A")]
    assert _shown(utts, 2) == "A"


def test_failed_row_without_structured_hidden():
    utts = [
        {
            "seq": 1,
            "speaker_type": "student",
            "persona_id": 1,
            "phase_idx": 0,
            "structured": None,
            "failed": True,
        }
    ]
    assert _shown(utts, 1) == ""


@pytest.mark.parametrize("speaker", ["teacher", "system"])
def test_teacher_and_system_rows_hidden(speaker):
    utts = [
        {"seq": 1, "speaker_type": speaker, "persona_id": None, "phase_idx": 0}
    ]
    assert _shown(utts, 1) == ""


_STUBS = """
const busy = false;
function regenerate() {}
function el(tag, className, text) {
    return {
        tag, className: className || "", textContent: text ?? "", children: [],
        append(...c) { this.children.push(...c); },
        addEventListener() {},
    };
}
const tree = n => [n.tag, n.className, n.textContent, n.children.map(tree)];
"""


def test_bubble_action_only_with_new_artifact():
    u = {
        "seq": 1,
        "speaker_type": "student",
        "persona_id": 1,
        "phase_idx": 0,
        "content": "(적는다)",
        "structured": {"action": "적는다", "utterance": "", "artifact": "A"},
    }
    script = (
        _STUBS
        + _fn(SIM, "shownArtifact(utts, u)")
        + _fn(SIM, "bubble(persona, u, regen)")
        + f"\nconst u = {json.dumps(u)};"
        + "\nconst state = {utterances: [u]};"
        + "\nconst box = bubble({color_key: 'c1'}, u, null);"
        + "\nconsole.log(JSON.stringify(box.children.map(tree)));"
    )
    assert _node(script) == [
        ["p", "note mb-0.5", "적는다", []],
        [
            "details",
            "note mt-1",
            "",
            [
                ["summary", "cursor-pointer", "산출물", []],
                ["p", "break-words", "A", []],
            ],
        ],
    ]


def test_templates_share_same_function():
    sig = "shownArtifact(utts, u)"
    assert _fn(SIM, sig) == _fn(TRANSCRIPT, sig)


def test_seat_summary_does_not_open_dm():
    src = SIM.read_text(encoding="utf-8")
    assert 'el("summary", "cursor-pointer", "산출물")' in src
    assert 'details.addEventListener("click", e => e.stopPropagation());' in src


def test_transcript_shows_artifact_line():
    src = TRANSCRIPT.read_text(encoding="utf-8")
    assert '"산출물: " + artifact' in src
