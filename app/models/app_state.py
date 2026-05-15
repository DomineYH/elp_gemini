from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func

from app.db import Base


class AppState(Base):
    """애플리케이션 상태 key-value 저장소"""

    __tablename__ = "app_state"

    key = Column(String(64), primary_key=True, comment="상태 키")
    value = Column(Text, nullable=False, comment="상태 값")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="마지막 갱신 시각",
    )
