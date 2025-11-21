"""
평가 기준 모델
CriteriaDocument 엔티티 및 관련 스키마 정의
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.db import Base


class ActiveCriteria(Base):
    """활성 평가 기준 단일 상태 관리 모델"""

    __tablename__ = "active_criteria"

    id = Column(
        Integer,
        primary_key=True,
        default=1,
        comment="항상 1 (단일 활성 상태 보장)",
    )
    criteria_document_id = Column(
        Integer,
        ForeignKey("criteria_documents.id"),
        nullable=True,
        unique=True,
    )
    activated_at = Column(DateTime, nullable=True)
    activated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    def __repr__(self):
        return (
            f"<ActiveCriteria(criteria_document_id="
            f"{self.criteria_document_id})>"
        )


class CriteriaAuditLog(Base):
    """평가 기준 감사 로그 모델"""

    __tablename__ = "criteria_audit_logs"

    id = Column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    action = Column(
        String(50),
        nullable=False,
        index=True,
        comment="upload | activate | deactivate | search",
    )
    criteria_document_id = Column(
        Integer,
        ForeignKey("criteria_documents.id"),
        nullable=True,
    )
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    detail = Column(String(1000), nullable=True)
    created_at = Column(
        DateTime, nullable=False, server_default=func.now()
    )

    def __repr__(self):
        return (
            f"<CriteriaAuditLog(id={self.id}, "
            f"action={self.action})>"
        )


class CriteriaDocument(Base):
    """평가 기준 문서 모델"""

    __tablename__ = "criteria_documents"

    id = Column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    title = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    vector_store_id = Column(
        String(255),
        nullable=False,
        unique=True,
        comment="Google File Search Store ID",
    )
    document_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Google File Search Document ID",
    )
    file_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Google File ID (독립적인 파일 객체)",
    )
    status = Column(
        String(50),
        nullable=False,
        default="uploaded",
        index=True,
        comment="uploaded | active | archived | error",
    )
    created_at = Column(
        DateTime, nullable=False, server_default=func.now()
    )
    activated_at = Column(DateTime, nullable=True)
    activated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    def __repr__(self):
        return (
            f"<CriteriaDocument(id={self.id}, "
            f"title={self.title}, status={self.status})>"
        )


# ===== Pydantic 스키마 =====


class CriteriaUploadRequest(BaseModel):
    """평가 기준 업로드 요청 스키마"""

    title: Optional[str] = Field(
        default=None,
        max_length=255,
        description="문서 제목 (선택, 미입력시 파일명 사용)",
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        """제목 검증"""
        if v is not None and v.strip() == "":
            raise ValueError("제목은 공백일 수 없습니다")
        return v.strip() if v else None


class CriteriaUploadResponse(BaseModel):
    """평가 기준 업로드 응답 스키마"""

    id: int = Field(..., description="기준 문서 ID")
    title: str = Field(..., description="문서 제목")
    file_path: str = Field(..., description="파일 저장 경로")
    mime_type: str = Field(..., description="파일 MIME 타입")
    file_size: int = Field(..., description="파일 크기 (bytes)")
    vector_store_id: str = Field(
        ..., description="Google File Search Store ID"
    )
    document_id: Optional[str] = Field(
        None, description="Google File Search Document ID"
    )
    file_id: Optional[str] = Field(
        None, description="Google File ID (독립적인 파일 객체)"
    )
    status: str = Field(..., description="문서 상태")
    created_at: datetime = Field(..., description="생성 시각")

    model_config = {"from_attributes": True}


class CriteriaDetailResponse(BaseModel):
    """평가 기준 상세 조회 응답 스키마"""

    id: int
    title: str
    file_path: str
    mime_type: str
    file_size: int
    vector_store_id: str
    document_id: Optional[str] = None
    file_id: Optional[str] = None
    status: str
    created_at: datetime
    activated_at: Optional[datetime] = None
    activated_by: Optional[int] = None

    model_config = {"from_attributes": True}


class CriteriaListResponse(BaseModel):
    """평가 기준 목록 조회 응답 스키마"""

    items: list[CriteriaDetailResponse] = Field(
        default_factory=list, description="기준 문서 목록"
    )
    total: int = Field(..., description="전체 문서 수")
    page: int = Field(default=1, ge=1, description="현재 페이지")
    page_size: int = Field(
        default=20, ge=1, le=100, description="페이지 크기"
    )


class CriteriaActivateResponse(BaseModel):
    """평가 기준 활성화 응답 스키마"""

    criteria_id: int = Field(..., description="활성화된 기준 문서 ID")
    title: str = Field(..., description="문서 제목")
    activated_at: datetime = Field(..., description="활성화 시각")
    activated_by: int = Field(..., description="활성화한 관리자 ID")

    model_config = {"from_attributes": True}
