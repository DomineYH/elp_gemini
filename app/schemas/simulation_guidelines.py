"""
관리자 피드백 지침 입력 (저장·미리보기 공용)
"""

from typing import Literal

from pydantic import BaseModel, Field

AspectKey = Literal[
    "achievement_standards",
    "udl",
    "digital_tools",
    "question_types",
    "formative_timing",
]


class GuidelineIn(BaseModel):
    enabled: bool
    required_aspects: list[AspectKey] = []
    criteria_ids: list[int] = []
    extra_instructions: str = Field("", max_length=4000)
