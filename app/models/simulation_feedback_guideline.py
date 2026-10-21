"""
관리자 피드백 지침 (버전마다 새 행, 최신 버전 = 현재 설정)
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
)
from sqlalchemy.sql import func

from app.db import Base


class SimulationFeedbackGuideline(Base):
    __tablename__ = "simulation_feedback_guidelines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(Integer, nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, server_default="0")
    required_aspects = Column(JSON, nullable=False)
    criteria_ids = Column(JSON, nullable=False)
    extra_instructions = Column(Text, nullable=False, server_default="")
    created_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
