"""
업로드 이벤트 모델
한 번의 업로드 액션 = 한 행. 분석 보고서와 1:1로 연결된다.
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


class LessonPlanUpload(Base):
    """수업 지도안 업로드 이벤트"""

    __tablename__ = "lessonplan_uploads"

    id = Column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    filename = Column(
        String(500),
        nullable=False,
        comment="서버 저장 파일명 ({username}_{original})",
    )
    original_filename = Column(
        String(500),
        nullable=True,
        comment="사용자 업로드 원본 파일명",
    )
    file_hash = Column(
        String(64),
        nullable=True,
        comment="SHA-256 of bytes — 향후 content-dedup 용",
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # 역방향 관계 (선택적)
    analysis_report = relationship(
        "AnalysisReport",
        back_populates="upload",
        uselist=False,
    )

    def __repr__(self):
        return (
            f"<LessonPlanUpload(id={self.id}, user_id={self.user_id}, "
            f"filename={self.filename})>"
        )
