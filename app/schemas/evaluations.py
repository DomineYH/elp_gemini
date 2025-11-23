"""
평가 스키마 (리팩토링)
파일 기반 평가 결과 관리
"""
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field


class RunEvaluationRequest(BaseModel):
    """평가 실행 요청"""

    lessonplan_filename: str = Field(
        ...,
        min_length=1,
        description="지도안 파일명"
    )
    evaluation_type: str = Field(
        default="general",
        description="평가 타입"
    )


class RunEvaluationResponse(BaseModel):
    """평가 실행 응답"""

    username: str = Field(
        ..., description="사용자 이름"
    )
    lessonplan_filename: str = Field(
        ..., description="지도안 파일명"
    )
    analysis_filename: str = Field(
        ..., description="분석 결과 파일명"
    )
    evaluation_type: str = Field(
        ..., description="평가 타입"
    )
    result_summary: Optional[str] = Field(
        None, description="결과 요약"
    )
    latency_ms: Optional[int] = Field(
        None, description="처리 시간 (ms)"
    )


class GetEvaluationResponse(BaseModel):
    """평가 결과 조회 응답"""

    filename: str = Field(
        ..., description="파일명"
    )
    content: str = Field(
        ..., description="마크다운 내용"
    )
    file_size: int = Field(
        ..., description="파일 크기 (bytes)"
    )
