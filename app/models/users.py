"""
사용자 모델
User 엔티티 정의
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class User(Base):
    """사용자 모델"""

    __tablename__ = "users"

    id = Column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    username = Column(
        String(255), unique=True, nullable=False, index=True
    )
    nickname = Column(String(255), nullable=False)
    email = Column(
        String(255), unique=True, nullable=True, index=True
    )
    hashed_password = Column(String(255), nullable=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    failed_login_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    locked_until = Column(DateTime, nullable=True)
    last_failed_login_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 관계
    chat_sessions = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    analysis_reports = relationship(
        "AnalysisReport",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    profile = relationship(
        "UserProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def __repr__(self):
        return (
            f"<User(id={self.id}, username={self.username}, "
            f"nickname={self.nickname}, is_admin={self.is_admin})>"
        )


# User를 직접 import하는 기존 코드 경로에서도 profile relationship 대상이
# SQLAlchemy class registry에 등록되도록 유지한다.
from app.models.user_profiles import UserProfile  # noqa: E402,F401
