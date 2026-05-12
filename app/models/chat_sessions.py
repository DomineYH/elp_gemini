"""
채팅 세션 모델
대화 세션 관리
"""
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class ChatSession(Base):
    """채팅 세션 모델"""

    __tablename__ = "chat_sessions"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )
    title = Column(
        String(255),
        nullable=True,
        comment="세션 제목 (선택사항)"
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )
    user_type = Column(
        String(50),
        nullable=True,
        index=True,
        comment=(
            "세션 세그먼트 라벨 "
            "(1학년, 2학년, 3학년, 4학년, 교사)"
        )
    )

    # 관계
    user = relationship("User", back_populates="chat_sessions")
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<ChatSession(id={self.id}, "
            f"user_id={self.user_id}, "
            f"title={self.title})>"
        )
