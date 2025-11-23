"""
채팅 메시지 모델
대화 메시지 저장
"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.db import Base


class MessageRole(str, enum.Enum):
    """메시지 역할"""
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(Base):
    """채팅 메시지 모델"""

    __tablename__ = "chat_messages"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True
    )
    session_id = Column(
        Integer,
        ForeignKey("chat_sessions.id"),
        nullable=False,
        index=True
    )
    role = Column(
        SQLEnum(MessageRole),
        nullable=False,
        comment="메시지 역할 (user/assistant)"
    )
    content = Column(
        Text,
        nullable=False,
        comment="메시지 내용"
    )
    model_name = Column(
        String(100),
        nullable=True,
        comment="사용된 모델 이름 (assistant만)"
    )
    citations = Column(
        JSON,
        nullable=True,
        comment="Citation 정보 (assistant만)"
    )
    used_criteria_ids = Column(
        Text,
        nullable=True,
        server_default="'[]'",
        comment="사용된 평가기준 ID 목록 (JSON 배열)"
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True
    )

    # 관계
    session = relationship(
        "ChatSession",
        back_populates="messages"
    )

    def __repr__(self):
        return (
            f"<ChatMessage(id={self.id}, "
            f"session_id={self.session_id}, "
            f"role={self.role.value})>"
        )
