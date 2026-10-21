"""국면 동의 계산 (#153, 순수 함수)."""

from types import SimpleNamespace

from app.services.simulation.agreement import compute_agreement

SUPPORT = "추가 지원 필요"


def _persona(pid, level="안정적 도달"):
    return SimpleNamespace(id=pid, adapted_level=level)


def _student(pid, ready, phase_idx=0):
    return SimpleNamespace(
        phase_idx=phase_idx,
        speaker_type="student",
        persona_id=pid,
        target_persona_id=None,
        structured=None if ready is None else {"ready_for_next": ready},
    )


def _teacher(source="user", target=None, phase_idx=0):
    return SimpleNamespace(
        phase_idx=phase_idx,
        speaker_type="teacher",
        persona_id=None,
        target_persona_id=target,
        structured={"source": source},
    )


def test_last_reaction_wins_and_counts():
    personas = [_persona(1), _persona(2)]
    utts = [_student(1, False), _student(2, True), _student(1, True)]
    assert compute_agreement(0, personas, utts) == {
        "phase_idx": 0,
        "agreed_persona_ids": [1, 2],
        "count": 2,
        "total": 2,
        "all_agreed": True,
    }
    utts.append(_student(2, False))
    result = compute_agreement(0, personas, utts)
    assert result["agreed_persona_ids"] == [1]
    assert result["all_agreed"] is False


def test_failed_latest_reaction_clears_consent_until_regenerated():
    personas = [_persona(1)]
    utts = [_student(1, True), _student(1, None)]
    assert compute_agreement(0, personas, utts)["agreed_persona_ids"] == []
    # 재생성은 실패한 행을 그 자리에서 고친다
    utts[1].structured = {"ready_for_next": True}
    assert compute_agreement(0, personas, utts)["agreed_persona_ids"] == [1]


def test_other_phase_is_ignored():
    personas = [_persona(1)]
    utts = [_student(1, True, phase_idx=0)]
    assert compute_agreement(1, personas, utts)["count"] == 0


def test_support_guard_until_user_teacher_turn():
    personas = [_persona(1, SUPPORT), _persona(2)]
    utts = [_teacher("plan"), _student(1, True), _student(2, True)]
    # 지도안 발문은 가드를 풀지 않는다
    assert compute_agreement(0, personas, utts)["agreed_persona_ids"] == [2]
    # 다른 학생에게 한 1:1 발화도 풀지 않는다
    utts.append(_teacher("user", target=2))
    assert compute_agreement(0, personas, utts)["agreed_persona_ids"] == [2]
    # 그 학생에게 한 1:1 발화는 푼다
    to_one = utts + [_teacher("user", target=1)]
    assert compute_agreement(0, personas, to_one)["all_agreed"] is True
    # 전체에게 한 발화도 푼다
    to_all = utts + [_teacher("user")]
    assert compute_agreement(0, personas, to_all)["all_agreed"] is True


def test_guard_needs_turn_in_same_phase():
    personas = [_persona(1, SUPPORT)]
    utts = [_teacher("user", phase_idx=0), _student(1, True, phase_idx=1)]
    assert compute_agreement(1, personas, utts)["count"] == 0
