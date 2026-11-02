"""
장면 동의 계산 (PLAN 2.6, #296, #301, 순수 함수)

학생마다 그 장면의 유효 반응(structured가 있는 행)을 seq 순으로 본다.
#301: 그 장면의 유효 행 중 하나라도 동의 조건을 만족하면 장면 끝까지 동의 유지.
막대 값은 최신 유효 행 기준.
동의 조건은 그 반응의 understanding(0~100)이 AGREE_THRESHOLD 이상인 것이다.
파싱 실패 행(structured 없음)은 건너뛰어 그 전 유효 반응이 최신이 된다(#254).
오개념이 있는 반응은 StudentReaction이 79 이하로 저장하므로 따로 해제하지 않는다.
understanding이 없는 #296 이전 행은 값 None이고, 동의는 그 행의
ready_for_next가 참이고 misconception이 비었을 때다. 같은 방식으로 한 번 동의면 유지.
"""

AGREE_THRESHOLD = 80  # 이해도 % 정수


def _row_agrees(s: dict) -> bool:
    value = s.get("understanding")
    if value is not None:
        return value >= AGREE_THRESHOLD
    # #296 이전 행(understanding 없음): 옛 규칙
    return bool(s.get("ready_for_next") and not s.get("misconception"))


def compute_agreement(phase_idx: int, personas, utterances) -> dict:
    """personas: id / utterances: seq 순 발화 행."""
    latest, agreed_once = {}, set()
    for u in utterances:
        if (
            u.phase_idx == phase_idx
            and u.speaker_type == "student"
            and u.structured is not None
        ):
            latest[u.persona_id] = u.structured
            if _row_agrees(u.structured):
                agreed_once.add(u.persona_id)
    understanding, agreed = {}, []
    for p in personas:
        s = latest.get(p.id)
        understanding[p.id] = s.get("understanding") if s else None
        if p.id in agreed_once:
            agreed.append(p.id)
    return {
        "phase_idx": phase_idx,
        "agreed_persona_ids": agreed,
        "understanding": understanding,
        "count": len(agreed),
        "total": len(personas),
        "all_agreed": len(agreed) == len(personas),
    }
