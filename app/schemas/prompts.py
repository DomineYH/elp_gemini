"""시스템 프롬프트 스키마"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SystemPromptResponse(BaseModel):
    """시스템 프롬프트 응답 모델"""

    id: int
    type: str = Field(..., description="프롬프트 타입 (qna, evaluation)")
    version: int = Field(..., description="버전 번호")
    content: str = Field(..., description="프롬프트 내용")
    is_active: bool = Field(..., description="활성 여부")
    created_by: int = Field(..., description="생성자 ID")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SystemPromptCreateRequest(BaseModel):
    """시스템 프롬프트 생성 요청 모델"""

    type: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_]+$",
        max_length=50,
        description="프롬프트 타입 (영문, 숫자, 밑줄만)",
    )
    content: str = Field(
        ...,
        min_length=10,
        max_length=50000,
        description="프롬프트 내용",
    )


class SystemPromptUpdateRequest(BaseModel):
    """시스템 프롬프트 수정 요청 모델"""

    content: str = Field(
        ...,
        min_length=10,
        max_length=50000,
        description="프롬프트 내용",
    )
