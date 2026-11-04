"""
시뮬레이션 구조화 출력 스키마 4종 (PLAN 2.3).
프롬프트에 JSON 예시로 반복하지 않는다.
"""

import re
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


class PhaseDraftItem(BaseModel):
    name: str
    minutes: int | None
    teacher_prompt: str
    task: str
    materials: str
    cautions: str
    source_span: str


class PhaseSplitResult(BaseModel):
    phases: list[PhaseDraftItem]


class AdaptationResult(BaseModel):
    strengths: list[str]
    weaknesses: list[str]
    behavior_summary: str
    speech_style: str
    support_needs: str


# '모름·막힘' 요약문은 오개념이 아니다(prompt.md sim_student 규칙, #302). 문장 끝만 본다.
# 명사형(-음/-함)과 '-다' 평서형(#305)을 동사 계열별로 묶는다: 모르다·헷갈리다·막히다·못 하다
# '잘못함/잘못했다'는 틀린 행동 서술이므로 남긴다(#311)
# 혼란·머뭇거림·망설임 요약도 막힘이다(#320)
# 추측으로 쓴 문장('…로 오해할 수 있다', '…것 같다', '…가능성이 있다')은 드러난 생각이 아니다(#317)
# '수 있다'는 인지 동사 뒤만 본다: '0으로 나눌 수 있다' 같은 단정은 실제 오개념일 수 있다
STUCK_SUMMARY = re.compile(
    r"(모름|모른다|모르고 ?있[음다]|모르겠[음다]"
    r"|헷갈림|헷갈린다|헷갈리고 ?있[음다]|헷갈려 ?(함|한다)"
    r"|막힘|막혔다|막혀 ?있[음다]"
    r"|(?<!잘)못 ?(함|한다|했다|했음|하고 ?있[음다]|하겠[음다])"
    r"|혼란스러워 ?(함|한다)|혼란스러워 ?하고 ?있[음다]|혼란스럽다|혼란스러움"
    r"|머뭇거림|머뭇거린다|머뭇거리고 ?있[음다]"
    r"|망설임|망설인다|망설이고 ?있[음다]"
    r"|((오해|착각|혼동|오인|생각|이해) ?[할될]|받아들일|여길|볼) ?수 ?있[음다]"
    r"|것 ?같[음다]"
    r"|가능성이 ?(있[음다]|높[음다])|우려가 ?있[음다])\s*\.?$"
)


class StudentReaction(BaseModel):
    action: str
    utterance: str
    artifact: str
    misconception: str
    ready_for_next: bool
    understanding: int  # 0~100, 이번 장면 과업·발문 핵심 이해 정도 (#296)
    confidence: float
    # 이 반응이 이번 장면 과업·발문에 대한 이해를 새로 보이거나 바꾸는가 (#306)
    on_task: bool

    @field_validator("understanding")
    @classmethod
    def _clamp(cls, v: int) -> int:
        # 범위 밖 값으로 반응 전체를 버리지 않는다
        return max(0, min(100, v))

    @model_validator(mode="after")
    def _cap_with_misconception(self):
        # 오개념이 드러난 반응은 동의 기준(80) 아래로 고정
        if self.misconception and self.understanding >= 80:
            self.understanding = 79
        # 상한은 원문 기준으로 먼저 걸고(막힘도 이해 부족), 텍스트만 비운다
        if STUCK_SUMMARY.search(self.misconception.strip()):
            self.misconception = ""
        return self


class RiskScenario(BaseModel):
    title: str
    scene: str
    evidence_type: Literal["입력 재현", "상호작용", "프로필·구조 결합"]


class UtteranceSuggestion(BaseModel):
    phase_idx: int
    actual: str
    suggested: str
    intent: str
    # 인용한 교사 발화의 대화록 # 번호. 서버가 actual을 원문으로 바꾼다.
    teacher_seq: int | None = None


class ChangeDirection(BaseModel):
    kind: Literal["발문", "비계", "자료", "평가"]
    content: str


class FeedbackResult(BaseModel):
    risk_scenarios: list[RiskScenario]
    utterance_suggestions: list[UtteranceSuggestion]
    progress_directions: list[str]
    change_directions: list[ChangeDirection]
