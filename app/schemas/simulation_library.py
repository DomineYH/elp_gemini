"""
내 학생 페르소나 입력 스키마 (HACHIMI-1M 정규화 필드, #158)
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.simulation.persona_pool import normalize_level

Subject = Annotated[str, Field(min_length=1, max_length=100)]
Narrative = Annotated[str, Field(max_length=2000)]
Stage = Annotated[str, Field(max_length=500)]


class DevelopmentStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    piaget_cognitive_stage: Stage
    erikson_psychosocial_stage: Stage
    kohlberg_moral_stage: Stage


class CustomPersonaIn(BaseModel):
    """id·academic_level_desc는 받지 않는다 (라이브러리 id를 쓰고 폼에 없음)."""

    model_config = ConfigDict(extra="forbid")

    age: int = Field(ge=6, le=13)
    gender: Literal["female", "male"]
    grade: int = Field(ge=1, le=6)
    academic_level: str
    development_stage: DevelopmentStage
    strong_subjects: list[Subject] = Field(max_length=10)
    weak_subjects: list[Subject] = Field(max_length=10)
    personality: Narrative
    values: Narrative
    social_relationships: Narrative
    creativity: Narrative
    mental_health: Narrative

    @field_validator("academic_level")
    @classmethod
    def _level(cls, value: str) -> str:
        return normalize_level(value)
