"""
데이터베이스 연결 및 초기화
SQLite with WAL mode, SQLAlchemy async support
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy import event
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


async def init_db():
    """
    데이터베이스 초기화
    - 모든 테이블 생성
    - 기본 데이터 시드
    """
    async with engine.begin() as conn:
        # 모든 테이블 생성
        await conn.run_sync(Base.metadata.create_all)

    # 기본 데이터 시드
    await seed_initial_data()


async def seed_initial_data():
    """
    초기 데이터 시드
    - 기본 관리자 계정
    - 기본 시스템 프롬프트
    - 기본 평가 템플릿
    """
    from app.models.users import User
    from app.models.prompts import SystemPrompt
    from passlib.context import CryptContext
    from sqlalchemy import select

    pwd_context = CryptContext(
        schemes=["bcrypt"], deprecated="auto"
    )

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
                    email="admin@example.com",
                    hashed_password=pwd_context.hash("admin_password"),
                    is_admin=True,
                )
                session.add(admin)
                await session.flush()

            # QnA 시스템 프롬프트가 이미 존재하는지 확인
            result = await session.execute(
                select(SystemPrompt).where(
                    SystemPrompt.type == "qna",
                    SystemPrompt.version == 1,
                )
            )
            qna_prompt = result.scalar_one_or_none()

            # QnA 프롬프트가 없으면 생성
            if not qna_prompt:
                qna_prompt = SystemPrompt(
                    type="qna",
                    version=1,
                    content=(
                        "당신은 문서 기반 질문답변을 돕는 유용한 AI "
                        "어시스턴트입니다. 제공된 문서 컨텍스트를 "
                        "기반으로 정확하고 유용한 답변을 제공하세요."
                    ),
                    is_active=True,
                    created_by=admin.id,
                )
                session.add(qna_prompt)

            # 평가 시스템 프롬프트가 이미 존재하는지 확인
            result = await session.execute(
                select(SystemPrompt).where(
                    SystemPrompt.type == "evaluation",
                    SystemPrompt.version == 1,
                )
            )
            eval_prompt = result.scalar_one_or_none()

            # 평가 프롬프트가 없으면 생성
            if not eval_prompt:
                eval_prompt = SystemPrompt(
                    type="evaluation",
                    version=1,
                    content=(
                        "당신은 문서 평가 전문가입니다. 제공된 "
                        "루브릭을 기반으로 문서를 체계적으로 "
                        "평가하고, 각 기준별 점수와 상세한 피드백을 "
                        "제공하세요."
                    ),
                    is_active=True,
                    created_by=admin.id,
                )
                session.add(eval_prompt)

            await session.commit()
        except Exception as e:
            await session.rollback()
            raise e
