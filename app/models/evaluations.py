"""평가 모델"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Float,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base


class EvaluationTemplate(Base):
    """평가 템플릿 모델"""

    __tablename__ = "evaluation_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(
        String(255), nullable=False, unique=True, index=True
    )
    description = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=False)
    file_search_file_id = Column(String(255), nullable=True)
    store_id = Column(String(255), nullable=True)
    is_active = Column(
        Boolean, nullable=False, default=True, index=True
    )
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
    evaluation_runs = relationship(
        "EvaluationRun", back_populates="template"
    )


class EvaluationRun(Base):
    """평가 실행 모델"""

    __tablename__ = "evaluation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(
        Integer, ForeignKey("documents.id"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    template_id = Column(
        Integer, ForeignKey("evaluation_templates.id"), nullable=False
    )
    prompt_id = Column(
        Integer, ForeignKey("system_prompts.id"), nullable=False
    )
    status = Column(
        String(50), nullable=False, default="pending", index=True
    )
    model_name = Column(String(100), nullable=False)
    started_at = Column(
        DateTime, nullable=False, server_default=func.now()
    )
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # 관계
    template = relationship(
        "EvaluationTemplate", back_populates="evaluation_runs"
    )
    report = relationship(
        "EvaluationReport", uselist=False, back_populates="run"
    )


class EvaluationReport(Base):
    """평가 보고서 모델"""

    __tablename__ = "evaluation_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        Integer,
        ForeignKey("evaluation_runs.id"),
        nullable=False,
        unique=True,
    )
    overall_score = Column(Float, nullable=True)
    criteria_scores = Column(JSON, nullable=True)
    feedback = Column(Text, nullable=False)
    improvement_suggestions = Column(Text, nullable=True)
    created_at = Column(
        DateTime, nullable=False, server_default=func.now()
    )

    # 관계
    run = relationship("EvaluationRun", back_populates="report")
