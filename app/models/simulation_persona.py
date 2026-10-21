"""
세션에 앉은 학생 페르소나 (원본·번안본 스냅샷)
"""

from sqlalchemy import JSON, Column, ForeignKey, Index, Integer, String

from app.db import Base


class SimulationPersona(Base):
    __tablename__ = "simulation_personas"
    __table_args__ = (
        Index(
            "uq_simulation_personas_session_seat",
            "session_id",
            "seat_idx",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer,
        ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    seat_idx = Column(Integer, nullable=False)  # 0부터
    display_name = Column(String(20), nullable=False)
    color_key = Column(String(4), nullable=False)  # f"p{seat_idx+1}"
    source = Column(String(16), nullable=False)  # 'dataset'|'custom'
    source_record_id = Column(Integer, nullable=False)
    raw_profile = Column(JSON, nullable=False)
    adapted_profile = Column(JSON, nullable=False)
    adapted_level = Column(String(20), nullable=False)
