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

    def __repr__(self):
        return (
            f"<User(id={self.id}, username={self.username}, "
            f"nickname={self.nickname}, is_admin={self.is_admin})>"
        )
