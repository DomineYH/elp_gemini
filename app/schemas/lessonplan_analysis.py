"""
수업 지도안 분석 스키마
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class LessonPlanAnalysisRequest(BaseModel):
    """분석 요청 스키마"""
    session_id: int = Field(..., description="채팅 세션 ID", gt=0)


class SavedReportInfo(BaseModel):
    """저장된 보고서 정보 스키마"""
    filename: str = Field(..., description="저장된 파일명")
    file_path: str = Field(..., description="저장된 파일 경로")
    timestamp: str = Field(..., description="저장 시간 (년월일시분초)")


class LessonPlanAnalysisResponse(BaseModel):
    """분석 응답 스키마"""
    success: bool = Field(..., description="성공 여부")
    report: Optional[str] = Field(None, description="Markdown 보고서")
    citations: Optional[Dict[str, Any]] = Field(
        None, description="Citation 정보"
    )
    latency_ms: Optional[int] = Field(None, description="응답 시간 (ms)")
    error: Optional[str] = Field(None, description="에러 메시지")
    saved_report: Optional[SavedReportInfo] = Field(
        None,
        description="저장된 보고서 파일 정보"
    )
    report_id: Optional[int] = Field(None, description="저장된 분석 보고서 ID")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "report": "# 수업 지도안 평가 보고서\n\n...",
                "citations": {
                    "used_criteria": ["평가기준 1", "평가기준 2"],
                    "grounding_chunks": [...]
                },
                "latency_ms": 12350,
                "saved_report": {
                    "filename": (
                        "111_20251128182530_수업지도안_"
                        "a1b2c3d4_reports.md"
                    ),
                    "file_path": (
                        "app/static/reports/111_20251128182530_"
                        "수업지도안_a1b2c3d4_reports.md"
                    ),
                    "timestamp": "20251128182530"
                },
                # 파일명 형식:
                # {username}_{년월일시간}_{업로드파일명}_{unique8}_reports.md
            }
        }
