"""QnA 스키마"""
from datetime import datetime
from pydantic import BaseModel, Field


class QAResponse(BaseModel):
    """QA 응답 모델"""

    question: str
    answer: str
    latency_ms: int | None


class QALogResponse(BaseModel):
    """QA 로그 응답 모델"""

    id: int
    question: str
    answer: str
    model_name: str
    latency_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class QARequest(BaseModel):
    """QA 요청 모델"""

    question: str = Field(..., min_length=1, max_length=5000)
