"""초대 코드 스키마"""
from datetime import datetime
from pydantic import BaseModel, Field


class InviteCodeCreate(BaseModel):
    """초대 코드 생성 요청"""

    user_type: str = Field(
        ..., description="사용자 유형"
    )
    count: int = Field(
        ..., ge=1, le=100, description="생성 수량"
    )


class InviteCodeResponse(BaseModel):
    """초대 코드 응답"""

    id: int
    code: str
    user_type: str
    is_active: bool
    is_used: bool = False
    created_at: datetime
    used_at: datetime | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, invite):
        """모델에서 응답 생성"""
        return cls(
            id=invite.id,
            code=invite.code,
            user_type=invite.user_type,
            is_active=invite.is_active,
            is_used=invite.user_id is not None,
            created_at=invite.created_at,
            used_at=invite.used_at,
        )


class InviteCodeListResponse(BaseModel):
    """초대 코드 목록 응답"""

    codes: list[InviteCodeResponse]
    total: int
    page: int
    page_size: int


class InviteCodeStats(BaseModel):
    """초대 코드 통계"""

    user_type: str
    total: int
    used: int
    unused: int
