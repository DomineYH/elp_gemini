"""QA 로그 모델"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base


class QALog(Base):
    """QA 로그 모델"""

    __tablename__ = "qa_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(
        Integer, ForeignKey("documents.id"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    prompt_id = Column(
        Integer, ForeignKey("system_prompts.id"), nullable=False
    )
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    model_name = Column(String(100), nullable=False)
    latency_ms = Column(Integer, nullable=True)

    # Gemini API 추가 필드
    citations = Column(
        JSON,
        nullable=True,
        comment="Citation 정보 (출처 메타데이터)",
    )
    sources_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="검색된 소스 개수",
    )

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # 관계
    document = relationship("Document", back_populates="qa_logs")
