"""
지도안 스키마
파일 기반 지도안 관리
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class LessonPlanUploadResponse(BaseModel):
    """지도안 업로드 응답"""

    filename: str = Field(..., description="저장된 파일명")
    original_filename: str = Field(..., description="원본 파일명")
    file_size: int = Field(..., description="파일 크기 (bytes)")
    saved_path: str = Field(..., description="저장 경로")
    upload_id: int = Field(..., description="업로드 이벤트 ID")
    file_hash: str = Field(
        ..., description="파일 SHA-256 (64자 hex)"
    )


class LessonPlanInfo(BaseModel):
    """지도안 정보"""

    filename: str = Field(
        ..., description="파일명"
    )
    file_size: int = Field(
        ..., description="파일 크기 (bytes)"
    )
    modified_time: datetime = Field(
        ..., description="수정 시간"
    )


class LessonPlanListResponse(BaseModel):
    """지도안 목록 응답"""

    username: str = Field(
        ..., description="사용자 이름"
    )
    lessonplans: list[LessonPlanInfo] = Field(
        default_factory=list,
        description="지도안 목록"
    )
    total_count: int = Field(
        ..., description="전체 개수"
    )
