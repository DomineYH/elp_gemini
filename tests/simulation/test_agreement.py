"""학생별 이해도 동의 계산 (#153, #296, 순수 함수).

래치 규칙은 폐기됐다(#296): 그 장면 최신 유효 반응의 이해도가 80 이상이면 동의.
"""

from types import SimpleNamespace

import pytest

from app.services.simulation.agreement import AGREE_THRESHOLD, compute_agreement


def _persona(pid, level="안정적 도달"):
    return SimpleNamespace(id=pid, adapted_level=level)


def _student(
    pid,
    understanding=None,
    ready=None,
    misconception="",
    phase_idx=0,
    failed=False,
):
    """understanding이 None이면 키를 넣지 않아 #296 이전 행을 흉내낸다."""
    structured = {"misconception": misconception}
    if understanding is not None:
        structured["understanding"] = understanding
    if ready is not None:
        structured["ready_for_next"] = ready
    return SimpleNamespace(
        phase_idx=phase_idx,
        speaker_type="student",
        persona_id=pid,
        target_persona_id=None,
        structured=None if failed else structured,
    )


def _one(utts):
    r = compute_agreement(0, [_persona(1)], utts)
    return r["agreed_persona_ids"], r["understanding"][1]


@pytest.mark.parametrize(
    "value, agreed", [(79, False), (80, True), (0, False), (100, True)]
)
def test_threshold_boundary(value, agreed):
    r = compute_agreement(0, [_persona(1)], [_student(1, value)])
    assert r["understanding"] == {1: value}
    assert r["agreed_persona_ids"] == ([1] if agreed else [])


def test_latest_wins_drop():
    assert _one([_student(1, 90), _student(1, 60)]) == ([], 60)


def test_latest_wins_rise():
    assert _one([_student(1, 40), _student(1, 85)]) == ([1], 85)


def test_failed_row_is_skipped():
    assert _one([_student(1, 85), _student(1, failed=True)]) == ([1], 85)
    assert _one([_student(1, failed=True)]) == ([], None)


def test_no_reaction_is_none():
    assert _one([]) == ([], None)


def test_legacy_row_fallback():
    assert _one([_student(1, ready=True)]) == ([1], None)
    assert _one([_student(1, ready=True, misconception="x")]) == ([], None)
    assert _one([_student(1, ready=False)]) == ([], None)


def test_legacy_then_new():
    assert _one([_student(1, ready=True), _student(1, 60)]) == ([], 60)


def test_other_phase_is_ignored():
    personas = [_persona(1)]
    utts = [_student(1, 85, phase_idx=0)]
    assert compute_agreement(1, personas, utts)["count"] == 0


def test_full_shape():
    personas = [_persona(1), _persona(2)]
    utts = [_student(1, 85), _student(2, 70)]
    assert compute_agreement(0, personas, utts) == {
        "phase_idx": 0,
        "agreed_persona_ids": [1],
        "understanding": {1: 85, 2: 70},
        "count": 1,
        "total": 2,
        "all_agreed": False,
    }


def test_threshold_constant_is_80():
    assert AGREE_THRESHOLD == 80
