"""
분석 보고서 모델
업로드된 지도안과 생성된 보고서의 연결 정보 관리
"""
from sqlalchemy import (
    Column,
    Index,
    Integer,
    String,
    Text,
    text,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class AnalysisReport(Base):
    """분석 보고서 모델"""

    __tablename__ = "analysis_reports"

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
    # 원본 지도안 파일 정보
    lessonplan_filename = Column(
        String(500),
        nullable=False,
        comment="원본 지도안 파일명 (예: 111_수업지도안.pdf)"
    )
    lessonplan_original_name = Column(
        String(500),
        nullable=True,
        comment="사용자가 업로드한 원본 파일명 (예: 수업지도안.pdf)"
    )
    # 생성된 보고서 파일 정보
    report_filename = Column(
        String(500),
        nullable=False,
        comment=(
            "보고서 파일명 "
            "(예: 111_20251128182530_수업지도안_a1b2c3d4_reports.md)"
        )
    )
    report_path = Column(
        String(1000),
        nullable=False,
        comment="보고서 파일 경로"
    )
    # 분석 메타 정보
    latency_ms = Column(
        Integer,
        nullable=True,
        comment="분석 소요 시간 (ms)"
    )
    upload_id = Column(
        Integer,
        ForeignKey("lessonplan_uploads.id"),
        nullable=True,
        comment="원본 업로드 이벤트 (1:1) — 중복 분석 방지 키",
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True
    )

    __table_args__ = (
        Index(
            'uq_analysis_reports_upload_id',
            'upload_id',
            unique=True,
            sqlite_where=text('upload_id IS NOT NULL'),
        ),
    )

    # 관계
    user = relationship("User", back_populates="analysis_reports")
    upload = relationship(
        "LessonPlanUpload", back_populates="analysis_report"
    )

    def __repr__(self):
        return (
            f"<AnalysisReport(id={self.id}, "
            f"user_id={self.user_id}, "
            f"lessonplan={self.lessonplan_original_name}, "
            f"report={self.report_filename})>"
        )
