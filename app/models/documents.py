"""
문서 모델
Document 엔티티 정의
"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class Document(Base):
    """문서 모델"""

    __tablename__ = "documents"

    id = Column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    random_key = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    status = Column(
        String(50), nullable=False, default="uploading", index=True
    )
    # Gemini File Search 관련 필드
    file_search_file_id = Column(
        String(255),
        nullable=True,
        comment="FileSearchStore Document ID (documents/xxxxx 형식)",
    )
    store_id = Column(
        String(255),
        nullable=True,
        comment="FileSearchStore ID (fileSearchStores/xxxxx 형식)",
    )
    uploaded_at = Column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 관계
    user = relationship("User", back_populates="documents")
    qa_logs = relationship(
        "QALog", back_populates="document", cascade="all, delete"
    )

    def __repr__(self):
        return (
            f"<Document(id={self.id}, title={self.title}, "
            f"status={self.status})>"
        )
