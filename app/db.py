"""
데이터베이스 연결 및 초기화
SQLite with WAL mode, SQLAlchemy async support
"""

import logging
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from app.config import settings

# SQLAlchemy Base
Base = declarative_base()

# Async engine 생성
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=NullPool,  # SQLite는 파일 기반이므로 NullPool 사용
)

# Async session factory
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


# SQLite pragma 설정 (WAL mode, foreign keys)
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """SQLite 연결 시 pragma 설정"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """데이터베이스 세션 의존성"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables(db_engine=None):
    """모델을 모두 import한 뒤 create_all. 기존 테이블은 건드리지 않는다."""
    # 모델이 app.db.Base를 import하므로 순환을 피해 함수 안에서 import
    import app.models  # noqa: F401
    import app.models.app_state  # noqa: F401
    import app.models.simulation_feedback_guideline  # noqa: F401
    import app.models.simulation_persona  # noqa: F401
    import app.models.simulation_persona_library  # noqa: F401
    import app.models.simulation_phase  # noqa: F401
    import app.models.simulation_session  # noqa: F401
    import app.models.simulation_utterance  # noqa: F401

    async with (db_engine or engine).begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def init_db():
    """
    데이터베이스 초기화
    - 모든 테이블 생성
    - 기본 데이터 시드
    """
    await create_tables()
    await seed_initial_admin()


async def seed_initial_admin() -> None:
    """
    초기 관리자 시드 (#264)
    - ADMIN_INITIAL_PASSWORD 우선, 없으면 개발 모드만 기본값
    - 운영 모드에서 환경변수가 없으면 건너뛰고 경고
    """
    from app.schemas.users import validate_password_strength

    password = settings.ADMIN_INITIAL_PASSWORD
    if password:
        try:
            validate_password_strength(password)
        except ValueError as e:
            # 값 자체는 메시지에 남기지 않는다
            raise RuntimeError(
                f"ADMIN_INITIAL_PASSWORD가 비밀번호 정책에 맞지 않습니다: {e}"
            ) from None
    elif settings.DEBUG:
        password = "admin1234"
    else:
        logging.getLogger(__name__).warning(
            "운영 모드: ADMIN_INITIAL_PASSWORD가 없어 "
            "관리자 계정을 만들지 않았습니다"
        )
        return
    await seed_initial_data(password)


async def seed_initial_data(password: str):
    """
    초기 데이터 시드
    - admin 계정이 없을 때만 생성 (기존 비밀번호는 덮어쓰지 않음)
    """
    from sqlalchemy import select

    from app.models.users import User
    from app.services.auth_service import AuthService

    async with async_session_maker() as session:
        try:
            # 기본 관리자가 이미 존재하는지 확인
            result = await session.execute(
                select(User).where(User.username == "admin")
            )
            admin = result.scalar_one_or_none()

            # 관리자가 없으면 생성
            if not admin:
                admin = User(
                    username="admin",
                    nickname="admin",
                    hashed_password=AuthService.hash_password(password),
                    is_admin=True,
                )
                session.add(admin)

            await session.commit()
        except Exception as e:
            await session.rollback()
            raise e
