"""
수업 지도안 분석 스키마
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class LessonPlanAnalysisRequest(BaseModel):
    """분석 요청 스키마"""
    session_id: int = Field(..., description="채팅 세션 ID", gt=0)


class LessonPlanAnalysisResponse(BaseModel):
    """분석 응답 스키마"""
    success: bool = Field(..., description="성공 여부")
    report: Optional[str] = Field(None, description="Markdown 보고서")
    citations: Optional[Dict[str, Any]] = Field(None, description="Citation 정보")
    latency_ms: Optional[int] = Field(None, description="응답 시간 (ms)")
    error: Optional[str] = Field(None, description="에러 메시지")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "report": "# 📚 수업 지도안 평가 보고서\n\n...",
                "citations": {
                    "used_criteria": ["평가기준 1", "평가기준 2"],
                    "grounding_chunks": [...]
                },
                "latency_ms": 12350
            }
        }
