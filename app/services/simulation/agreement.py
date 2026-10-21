"""
국면 동의 계산 (PLAN 2.6, 순수 함수)

페르소나별로 그 국면 마지막 학생 발화의 ready_for_next를 쓴다.
마지막 발화가 파싱 실패(structured 없음)면 동의하지 않은 것으로 본다.
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
            ready[u.persona_id] = bool(
                (u.structured or {}).get("ready_for_next")
            )
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
