"""
분석 보고서 스키마
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class AnalysisReportItem(BaseModel):
    """분석 보고서 항목 스키마"""
    id: int = Field(..., description="보고서 ID")
    lessonplan_filename: str = Field(..., description="지도안 파일명")
    lessonplan_original_name: Optional[str] = Field(
        None, description="원본 지도안 파일명"
    )
    report_filename: str = Field(..., description="보고서 파일명")
    report_path: str = Field(..., description="보고서 파일 경로")
    latency_ms: Optional[int] = Field(None, description="분석 소요 시간 (ms)")
    created_at: datetime = Field(..., description="생성 일시")

    class Config:
        from_attributes = True


class AnalysisReportListResponse(BaseModel):
    """분석 보고서 목록 응답 스키마"""
    username: str = Field(..., description="사용자명")
    reports: List[AnalysisReportItem] = Field(
        default_factory=list, description="보고서 목록"
    )
    total_count: int = Field(..., description="총 보고서 수")

    class Config:
        json_schema_extra = {
            "example": {
                "username": "111",
                "reports": [
                    {
                        "id": 1,
                        "lessonplan_filename": "111_수업지도안.pdf",
                        "lessonplan_original_name": "수업지도안.pdf",
                        "report_filename": (
                            "111_20251128182530_수업지도안_"
                            "a1b2c3d4_reports.md"
                        ),
                        "report_path": (
                            "app/static/reports/111_20251128182530_"
                            "수업지도안_a1b2c3d4_reports.md"
                        ),
                        "latency_ms": 45000,
                        "created_at": "2025-11-28T18:25:30"
                    }
                ],
                "total_count": 1
            }
        }
