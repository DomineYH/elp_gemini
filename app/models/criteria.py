"""
평가기준 모델
Criteria 엔티티 정의
"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    BigInteger,
)
from sqlalchemy.sql import func

from app.db import Base


class Criteria(Base):
    """평가기준 모델"""

    __tablename__ = "criteria"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True
    )
    title = Column(
        String(255),
        nullable=False,
        comment="평가기준 파일명/제목"
    )
    document_id = Column(
        String(500),
        unique=True,
        nullable=True,  # 업로드 시에는 None, 활성화 확정 후 생성
        index=True,
        comment="Vector Store 문서 ID"
    )
    file_size = Column(
        BigInteger,
        nullable=False,
        comment="파일 크기 (바이트)"
    )
    file_path = Column(
        String(500),
        nullable=False,
        comment="로컬 파일 시스템 경로"
    )
    status = Column(
        String(50),
        nullable=False,
        default="uploaded",
        index=True,
        comment="상태: uploaded, active, archived"
    )
    uploaded_by = Column(
        String(255),
        nullable=False,
        comment="업로드한 관리자 사용자명"
    )
    activated_at = Column(
        DateTime,
        nullable=True,
        comment="활성화된 시각 (active 상태일 때만 값 존재)"
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
    synced_at = Column(
        DateTime,
        nullable=True,
        comment="Vector Store 동기화 시각"
    )

    def __repr__(self):
        return (
            f"<Criteria(id={self.id}, "
            f"title={self.title}, "
            f"status={self.status})>"
        )
