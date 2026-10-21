"""
시뮬레이션 구조화 출력 스키마 4종 (PLAN 2.3).
프롬프트에 JSON 예시로 반복하지 않는다.
"""

from typing import Literal

from pydantic import BaseModel


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


class StudentReaction(BaseModel):
    action: str
    utterance: str
    artifact: str
    misconception: str
    ready_for_next: bool
    confidence: float


class RiskScenario(BaseModel):
    title: str
    scene: str
    evidence_type: Literal["입력 재현", "상호작용", "프로필·구조 결합"]


class UtteranceSuggestion(BaseModel):
    phase_idx: int
    actual: str
    suggested: str
    intent: str


class ChangeDirection(BaseModel):
    kind: Literal["발문", "비계", "자료", "평가"]
    content: str


class FeedbackResult(BaseModel):
    risk_scenarios: list[RiskScenario]
    utterance_suggestions: list[UtteranceSuggestion]
    progress_directions: list[str]
    change_directions: list[ChangeDirection]
