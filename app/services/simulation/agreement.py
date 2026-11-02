"""
장면 동의 계산 (PLAN 2.6, #296, 순수 함수)

학생마다 그 장면의 최신 유효 반응(structured가 있는 행)만 본다. 래치는 없다.
그 반응의 understanding(0~100)이 AGREE_THRESHOLD 이상이면 동의, 낮아지면 다시 미동의.
파싱 실패 행(structured 없음)은 건너뛰어 그 전 유효 반응이 최신이 된다(#254).
오개념이 있는 반응은 StudentReaction이 79 이하로 저장하므로 따로 해제하지 않는다.
understanding이 없는 #296 이전 행은 값 None이고, 동의는 그 행의
ready_for_next가 참이고 misconception이 비었을 때다.
"""

AGREE_THRESHOLD = 80  # 이해도 % 정수


def compute_agreement(phase_idx: int, personas, utterances) -> dict:
    """personas: id / utterances: seq 순 발화 행."""
    latest = {}
    for u in utterances:
        if (
            u.phase_idx == phase_idx
            and u.speaker_type == "student"
            and u.structured is not None
        ):
            latest[u.persona_id] = u.structured
    understanding, agreed = {}, []
    for p in personas:
        s = latest.get(p.id)
        value = s.get("understanding") if s else None
        understanding[p.id] = value
        if value is not None:
            ok = value >= AGREE_THRESHOLD
        else:
            ok = bool(
                s and s.get("ready_for_next") and not s.get("misconception")
            )
        if ok:
            agreed.append(p.id)
    return {
        "phase_idx": phase_idx,
        "agreed_persona_ids": agreed,
        "understanding": understanding,
        "count": len(agreed),
        "total": len(personas),
        "all_agreed": len(agreed) == len(personas),
    }
