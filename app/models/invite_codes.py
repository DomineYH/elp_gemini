"""
초대 코드 모델
InviteCode 엔티티 정의
"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class InviteCode(Base):
    """초대 코드 모델"""

    __tablename__ = "invite_codes"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    code = Column(
        String(6),
        unique=True,
        nullable=False,
        index=True,
    )
    user_type = Column(
        String(20),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
    )
    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    used_at = Column(DateTime, nullable=True)

    # 관계
    user = relationship("User", foreign_keys=[user_id])
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return (
            f"<InviteCode(id={self.id}, "
            f"code={self.code}, "
            f"user_type={self.user_type})>"
        )
