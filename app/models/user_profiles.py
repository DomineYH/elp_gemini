"""
사용자 프로필 모델

이메일/비밀번호 인증 주체인 User와 분리하여 역할별 연구/분류
메타데이터를 보관한다.
"""
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class UserProfile(Base):
    """일반 사용자 1:1 프로필 모델"""

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "role IN ('teacher', 'preservice_teacher')",
            name="ck_user_profiles_role",
        ),
        CheckConstraint(
            "teacher_career_years IS NULL "
            "OR teacher_career_years >= 0",
            name="ck_user_profiles_teacher_career_years_non_negative",
        ),
        CheckConstraint(
            "preservice_grade IS NULL "
            "OR preservice_grade BETWEEN 1 AND 4",
            name="ck_user_profiles_preservice_grade_range",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    role = Column(String(50), nullable=False)
    teacher_region = Column(String(50), nullable=True)
    teacher_career_years = Column(Integer, nullable=True)
    preservice_university_region = Column(
        String(50), nullable=True
    )
    preservice_grade = Column(Integer, nullable=True)
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
    user = relationship("User", back_populates="profile")

    def __repr__(self):
        return (
            f"<UserProfile(id={self.id}, user_id={self.user_id}, "
            f"role={self.role})>"
        )
