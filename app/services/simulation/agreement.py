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
#358: 다짐뿐인 후속 반응(structured["pledge"])도 오개념이 없으면 동의다. 이해도는 그대로다.
pledged_persona_ids는 이해도 도달 없이 다짐으로만 동의한 학생이다.
"""

AGREE_THRESHOLD = 80  # 이해도 % 정수


def _row_agrees(s: dict) -> bool:
    value = s.get("understanding")
    if value is not None:
        return value >= AGREE_THRESHOLD
    # #296 이전 행(understanding 없음): 옛 규칙
    return bool(s.get("ready_for_next") and not s.get("misconception"))


def _row_pledged(s: dict) -> bool:
    return bool(s.get("pledge") and not s.get("misconception"))


def compute_agreement(phase_idx: int, personas, utterances) -> dict:
    """personas: id / utterances: seq 순 발화 행."""
    latest, reached, pledged = {}, set(), set()
    for u in utterances:
        if (
            u.phase_idx == phase_idx
            and u.speaker_type == "student"
            and u.structured is not None
        ):
            latest[u.persona_id] = u.structured
            if _row_agrees(u.structured):
                reached.add(u.persona_id)
            if _row_pledged(u.structured):
                pledged.add(u.persona_id)
    understanding, agreed = {}, []
    for p in personas:
        s = latest.get(p.id)
        understanding[p.id] = s.get("understanding") if s else None
        if p.id in reached or p.id in pledged:
            agreed.append(p.id)
    return {
        "phase_idx": phase_idx,
        "agreed_persona_ids": agreed,
        "pledged_persona_ids": [
            p.id for p in personas if p.id in pledged and p.id not in reached
        ],
        "understanding": understanding,
        "count": len(agreed),
        "total": len(personas),
        "all_agreed": len(agreed) == len(personas),
    }
