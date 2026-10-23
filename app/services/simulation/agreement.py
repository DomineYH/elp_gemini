"""
국면 동의 계산 (PLAN 2.6, 순수 함수)

페르소나별로 그 국면 학생 발화를 차례로 보며 동의를 래치한다.
misconception이 비어 있지 않으면 미동의, 아니면 ready_for_next=true일 때 동의.
false이고 오개념이 없거나 파싱 실패(structured 없음)면 이전 상태를 유지한다.
오개념 없이 "모르겠어요"만 하는 반응은 래치를 풀지 못한다(프롬프트가 1차 방어).
번안 수준이 "추가 지원 필요"면 그 학생 또는 전체를 향한 교사 발화(source=user)가
그 국면에 있기 전까지 false로 덮어쓴다.
"""

SUPPORT_LEVEL = "추가 지원 필요"


def compute_agreement(phase_idx: int, personas, utterances) -> dict:
    """personas: id, adapted_level / utterances: seq 순 발화 행."""
    in_phase = [u for u in utterances if u.phase_idx == phase_idx]
    ready = {}
    reached = set()
    reached_all = False
    for u in in_phase:
        if u.speaker_type == "student":
            s = u.structured or {}
            if s.get("misconception"):
                ready[u.persona_id] = False
            elif s.get("ready_for_next"):
                ready[u.persona_id] = True
        elif (
            u.speaker_type == "teacher"
            and (u.structured or {}).get("source") == "user"
        ):
            if u.target_persona_id is None:
                reached_all = True
            else:
                reached.add(u.target_persona_id)
    agreed = [
        p.id
        for p in personas
        if ready.get(p.id)
        and (p.adapted_level != SUPPORT_LEVEL or reached_all or p.id in reached)
    ]
    return {
        "phase_idx": phase_idx,
        "agreed_persona_ids": agreed,
        "count": len(agreed),
        "total": len(personas),
        "all_agreed": len(agreed) == len(personas),
    }
