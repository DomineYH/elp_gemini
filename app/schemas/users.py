"""
사용자 스키마
API 요청/응답 모델
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    """사용자 응답 모델"""

    id: int
    username: str
    nickname: str
    email: EmailStr | None = None
    is_admin: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserLogin(BaseModel):
    """로그인 요청 모델"""

    username: str = Field(..., description="사용자 ID")
    nickname: str = Field(..., description="닉네임")


class UserCreate(BaseModel):
    """사용자 생성 요청 모델"""

    username: str = Field(..., description="사용자 ID")
    nickname: str = Field(..., description="닉네임")
    email: EmailStr | None = Field(None, description="이메일 주소")
    password: str | None = Field(
        None,
        min_length=8,
        description="비밀번호 (최소 8자, 대소문자 및 숫자 포함)",
    )
    is_admin: bool = Field(default=False, description="관리자 여부")
