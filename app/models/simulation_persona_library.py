"""
사용자가 직접 만든 학생 페르소나 (원본·번안본, 수정 없음)
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db import Base


class SimulationPersonaLibraryItem(Base):
    __tablename__ = "simulation_persona_library"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_profile = Column(JSON, nullable=False)
    adapted_profile = Column(JSON, nullable=False)
    adapted_level = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
