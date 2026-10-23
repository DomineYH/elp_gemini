"""
수업 시뮬레이션 스키마
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings
from app.services.simulation.persona_pool import MIN_PERSONAS

# 지도안 발문을 그대로 발화로 보낼 수 있도록 두 상한을 같이 둔다
TEACHER_PROMPT_MAX = 2000

Level = Literal["High", "Average", "Low", "Poor"]


class Candidate(BaseModel):
    """설정 화면 후보 페르소나 (번안 전)"""

    ref: str
    source: Literal["dataset", "custom"]
    pseudonym: str
    grade: int
    level: Level
    level_label: str
    strong_subjects: list[str]
    weak_subjects: list[str]
    behavior_summary: str


class CandidatesResponse(BaseModel):
    seed: int
    candidates: list[Candidate]


class PhaseIn(BaseModel):
    """설정 화면에서 편집한 국면 1개"""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=50)
    minutes: int | None = Field(None, ge=0, le=180)
    teacher_prompt: str = Field(min_length=1, max_length=TEACHER_PROMPT_MAX)
    task: str = Field("", max_length=2000)
    materials: str = Field("", max_length=4000)
    cautions: str = Field("", max_length=4000)
    source_span: str = Field("", max_length=4000)


class Phase(PhaseIn):
    # 출력 모델: strip 이전에 저장된 공백 국면도 읽을 수 있어야 한다.
    model_config = ConfigDict(str_strip_whitespace=False)

    idx: int


class PersonaPick(BaseModel):
    ref: str
    pseudonym: str


class RandomPick(BaseModel):
    n: int = Field(ge=MIN_PERSONAS, le=settings.SIM_MAX_PERSONAS)
    grade: Literal["all", "5", "6"] = "all"
    level: Literal["all"] | Level = "all"
    seed: int | None = None


class CreateSessionRequest(BaseModel):
    """personas 또는 random 중 하나만"""

    personas: list[PersonaPick] | None = Field(
        None, min_length=MIN_PERSONAS, max_length=settings.SIM_MAX_PERSONAS
    )
    random: RandomPick | None = None
    phases: list[PhaseIn] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _one_selection(self):
        if (self.personas is None) == (self.random is None):
            raise ValueError("personas와 random 중 하나만 보내야 합니다")
        if self.personas is not None:
            refs = [p.ref for p in self.personas]
            if len(set(refs)) != len(refs):
                raise ValueError("ref가 중복되었습니다")
        return self


class PersonaLimitIn(BaseModel):
    max_personas: int = Field(ge=MIN_PERSONAS, le=settings.SIM_MAX_PERSONAS)


class PersonaLimitOut(BaseModel):
    max_personas: int
    min: int
    absolute_max: int
    configured: bool


class Persona(BaseModel):
    """좌석의 페르소나 (원본 프로필은 사용자에게 보내지 않는다)"""

    id: int
    seat_idx: int
    display_name: str
    color_key: str
    source: Literal["dataset", "custom"]
    source_record_id: int
    adapted_level: str
    adapted_profile: dict


class Utterance(BaseModel):
    id: int
    seq: int
    phase_idx: int
    speaker_type: Literal["teacher", "student", "system"]
    persona_id: int | None
    target_persona_id: int | None
    content: str
    structured: dict | None
    failed: bool
    model_name: str | None
    latency_ms: int | None
    created_at: datetime


class SessionInfo(BaseModel):
    id: int
    status: str
    current_phase_idx: int
    persona_count: int
    model_name: str
    upload_id: int
    created_at: datetime
    finished_at: datetime | None
    teacher_turns_used: int
    teacher_turns_max: int
    has_feedback: bool
    is_latest_upload: bool


class Agreement(BaseModel):
    phase_idx: int
    agreed_persona_ids: list[int]
    count: int
    total: int
    all_agreed: bool


class SessionState(BaseModel):
    session: SessionInfo
    phases: list[Phase]
    personas: list[Persona]
    utterances: list[Utterance]
    agreement: Agreement


class TurnResult(BaseModel):
    utterances: list[Utterance]
    failed_persona_ids: list[int]
    agreement: Agreement
    teacher_turns_used: int


class SayRequest(BaseModel):
    """target_persona_id가 없으면 전체에게"""

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=TEACHER_PROMPT_MAX)
    target_persona_id: int | None = None


class RegenerateRequest(BaseModel):
    persona_id: int


class AdvanceRequest(BaseModel):
    mode: Literal["agree", "skip"]


class AdvanceResult(BaseModel):
    status: str
    current_phase_idx: int
    next_phase: Phase | None


class FinishResult(BaseModel):
    status: Literal["finished"]


class SessionSummary(BaseModel):
    id: int
    created_at: datetime
    persona_count: int
    status: str
    has_feedback: bool
    upload_id: int
    current_phase_idx: int
    phase_count: int


class SessionList(BaseModel):
    sessions: list[SessionSummary]
