"""평가 스키마"""
from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class EvaluationRunResponse(BaseModel):
    """평가 실행 응답 모델"""

    id: int
    document_id: int
    user_id: int
    template_id: int
    status: str
    model_name: str
    started_at: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]

    model_config = {"from_attributes": True}


class EvaluationReportResponse(BaseModel):
    """평가 보고서 응답 모델"""

    id: int
    run_id: int
    overall_score: Optional[float]
    criteria_scores: Optional[Dict[str, Any]]
    feedback: str
    improvement_suggestions: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class EvaluationRequest(BaseModel):
    """평가 요청 모델"""

    template_id: int = Field(..., description="평가 템플릿 ID")
