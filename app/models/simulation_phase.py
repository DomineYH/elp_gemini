"""
수업 시뮬레이션 국면 (세션마다 편집된 지도안 국면의 사본)
"""

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text

from app.db import Base


class SimulationPhase(Base):
    __tablename__ = "simulation_phases"
    __table_args__ = (
        Index(
            "uq_simulation_phases_session_idx",
            "session_id",
            "idx",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer,
        ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    idx = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False)
    minutes = Column(Integer, nullable=True)
    teacher_prompt = Column(Text, nullable=False, server_default="")
    task = Column(Text, nullable=False, server_default="")
    materials = Column(Text, nullable=False, server_default="")
    cautions = Column(Text, nullable=False, server_default="")
    source_span = Column(Text, nullable=False, server_default="")
