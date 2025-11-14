"""시스템 프롬프트 모델"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from app.db import Base


class SystemPrompt(Base):
    """시스템 프롬프트 모델"""

    __tablename__ = "system_prompts"
    __table_args__ = (
        UniqueConstraint("type", "version", name="uq_type_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)
    created_by = Column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at = Column(
        DateTime, nullable=False, server_default=func.now()
    )
