"""
사용자 스키마
API 요청/응답 모델
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.constants import (
    PRESERVICE_UNIVERSITY_REGIONS,
    TEACHER_REGIONS,
)


def normalize_email_address(value: str) -> str:
    """이메일 비교/저장용 정규화: 공백 제거 + 소문자화."""
    if value is None:
        return ""
    return str(value).strip().lower()


def validate_password_strength(password: str) -> str:
    """일반 사용자 비밀번호 정책 검증."""
    if not isinstance(password, str):
        raise ValueError("비밀번호는 문자열이어야 합니다.")
    if len(password) < 8:
        raise ValueError("비밀번호는 최소 8자 이상이어야 합니다.")
    if not any(char.isalpha() for char in password):
        raise ValueError("비밀번호에는 문자가 포함되어야 합니다.")
    if not any(char.isdigit() for char in password):
        raise ValueError("비밀번호에는 숫자가 포함되어야 합니다.")
    return password


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

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        """저장 전 이메일 정규화."""
        if value is None:
            return None
        return normalize_email_address(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str | None) -> str | None:
        """비밀번호가 제공된 경우 공통 정책을 적용한다."""
        if value is None:
            return None
        return validate_password_strength(value)


class EmailPasswordLogin(BaseModel):
    """일반 사용자 이메일+비밀번호 로그인 요청 모델"""

    email: EmailStr = Field(..., description="이메일 주소")
    password: str = Field(..., min_length=1, description="비밀번호")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """로그인 식별용 이메일 정규화."""
        return normalize_email_address(value)


class TeacherRegistration(BaseModel):
    """현직 교사 등록 요청 모델"""

    email: EmailStr = Field(..., description="이메일 주소")
    role: Literal["teacher"] = Field(
        default="teacher",
        description="사용자 인증 역할",
    )
    teacher_region: str = Field(..., description="교사 지역")
    teacher_career_years: int = Field(
        ...,
        ge=0,
        description="교직 경력 연수",
    )
    password: str = Field(
        ...,
        min_length=8,
        description="비밀번호 (최소 8자, 문자 및 숫자 포함)",
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """저장 전 이메일 정규화."""
        return normalize_email_address(value)

    @field_validator("teacher_region", mode="before")
    @classmethod
    def normalize_teacher_region(cls, value: str) -> str:
        """지역 입력 주변 공백 제거."""
        return str(value).strip()

    @field_validator("teacher_region")
    @classmethod
    def validate_teacher_region(cls, value: str) -> str:
        """허용된 교사 지역만 받는다."""
        if value not in TEACHER_REGIONS:
            raise ValueError("허용되지 않는 교사 지역입니다.")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """공통 비밀번호 정책을 적용한다."""
        return validate_password_strength(value)


class PreserviceTeacherRegistration(BaseModel):
    """예비교사 등록 요청 모델"""

    email: EmailStr = Field(..., description="이메일 주소")
    role: Literal["preservice_teacher"] = Field(
        default="preservice_teacher",
        description="사용자 인증 역할",
    )
    preservice_university_region: str = Field(
        ...,
        description="대학교 지역",
    )
    preservice_grade: int = Field(
        ...,
        ge=1,
        le=4,
        description="학년",
    )
    password: str = Field(
        ...,
        min_length=8,
        description="비밀번호 (최소 8자, 문자 및 숫자 포함)",
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """저장 전 이메일 정규화."""
        return normalize_email_address(value)

    @field_validator("preservice_university_region", mode="before")
    @classmethod
    def normalize_university_region(cls, value: str) -> str:
        """대학교 지역 입력 주변 공백 제거."""
        return str(value).strip()

    @field_validator("preservice_university_region")
    @classmethod
    def validate_university_region(cls, value: str) -> str:
        """허용된 예비교사 대학교 지역만 받는다."""
        if value not in PRESERVICE_UNIVERSITY_REGIONS:
            raise ValueError("허용되지 않는 대학교 지역입니다.")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """공통 비밀번호 정책을 적용한다."""
        return validate_password_strength(value)
