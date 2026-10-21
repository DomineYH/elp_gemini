"""
시뮬레이션 발화 (교사·학생·시스템). seq는 세션 안에서 1부터.
"""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.db import Base


class SimulationUtterance(Base):
    __tablename__ = "simulation_utterances"
    __table_args__ = (
        Index(
            "uq_simulation_utterances_session_seq",
            "session_id",
            "seq",
            unique=True,
        ),
        Index(
            "ix_simulation_utterances_session_phase",
            "session_id",
            "phase_idx",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer,
        ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_idx = Column(Integer, nullable=False)
    seq = Column(Integer, nullable=False)
    speaker_type = Column(String(10), nullable=False)
    persona_id = Column(
        Integer,
        ForeignKey("simulation_personas.id", ondelete="CASCADE"),
        nullable=True,
    )
    target_persona_id = Column(
        Integer,
        ForeignKey("simulation_personas.id", ondelete="CASCADE"),
        nullable=True,
    )
    content = Column(Text, nullable=False)
    # 학생: StudentReaction.model_dump(), NULL = 파싱 실패
    structured = Column(JSON, nullable=True)
    model_name = Column(String(100), nullable=True)
    temperature = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
