"""
수업 시뮬레이션 세션 (한 번의 시뮬레이션 실행)
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db import Base


class SimulationSession(Base):
    __tablename__ = "simulation_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    upload_id = Column(
        Integer,
        ForeignKey("lessonplan_uploads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 'setup'|'running'|'finished' (생성 시 'running', 'setup'은 예약)
    status = Column(String(16), nullable=False, server_default="running")
    current_phase_idx = Column(Integer, nullable=False, server_default="0")
    persona_count = Column(Integer, nullable=False)
    model_name = Column(String(100), nullable=False)
    feedback_json = Column(JSON, nullable=True)
    feedback_report_path = Column(String(1000), nullable=True)
    feedback_guideline_version = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)
