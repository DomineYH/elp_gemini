"""
수업 시뮬레이션 스키마
"""

from typing import Literal

from pydantic import BaseModel

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
