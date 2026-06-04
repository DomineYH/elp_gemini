"""
사용자 스키마
API 요청/응답 모델
"""
import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

# 사용자 지정 id 정책 (Issue #90)
# - 영문 + 숫자만, 9자 이하(10자 미만)
# - 대소문자 무시 고유(소문자 정규화하여 저장/비교)
# - 예약어 금지
USER_ID_PATTERN = re.compile(r"^[a-z0-9]{1,9}$")
RESERVED_USER_IDS = frozenset(
    {
        "admin",
        "administrator",
        "root",
        "system",
        "teacher",
        "preservice_teacher",
    }
)


def normalize_email_address(value: str) -> str:
    """이메일 비교/저장용 정규화: 공백 제거 + 소문자화."""
    if value is None:
        return ""
    return str(value).strip().lower()


def normalize_user_id(value: str | None) -> str:
    """사용자 지정 id 정규화: 공백 제거 + 소문자화."""
    if value is None:
        return ""
    return str(value).strip().lower()


def validate_user_id(value: str | None) -> str:
    """사용자 지정 id 정책 검증 후 정규화된 값을 반환.

    영문/숫자 9자 이하만 허용하며 예약어는 거부한다.
    """
    normalized = normalize_user_id(value)
    if not USER_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            "아이디는 영문/숫자 9자 이하로 입력해주세요."
        )
    if normalized in RESERVED_USER_IDS:
        raise ValueError("사용할 수 없는 아이디입니다.")
    return normalized


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


class IdPasswordLogin(BaseModel):
    """일반 사용자 id+비밀번호 로그인 요청 모델 (Issue #90)"""

    user_id: str = Field(..., description="사용자 지정 아이디")
    password: str = Field(..., min_length=1, description="비밀번호")

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        """로그인 식별용 id 정규화(대소문자 무시)."""
        return normalize_user_id(value)


class RegularUserRegistration(BaseModel):
    """일반 사용자 등록 요청 모델 (Issue #90, id+비밀번호)"""

    user_id: str = Field(..., description="사용자 지정 아이디")
    password: str = Field(
        ...,
        min_length=8,
        description="비밀번호 (최소 8자, 문자 및 숫자 포함)",
    )

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        """저장 전 id 정규화."""
        return normalize_user_id(value)

    @field_validator("user_id")
    @classmethod
    def check_user_id(cls, value: str) -> str:
        """id 형식/예약어 정책을 적용한다."""
        return validate_user_id(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """공통 비밀번호 정책을 적용한다."""
        return validate_password_strength(value)
