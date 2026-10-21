"""시뮬레이션 테이블 마이그레이션 (#152, ADR 0001)."""

import pytest
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.db import Base
from app.migrations import ensure_simulation_tables
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_persona import SimulationPersona
from app.models.simulation_session import SimulationSession
from app.models.simulation_utterance import SimulationUtterance
from app.models.users import User

from .conftest import run

SIM_TABLES = {
    "simulation_sessions",
    "simulation_phases",
    "simulation_personas",
    "simulation_utterances",
    "simulation_persona_library",
    "simulation_feedback_guidelines",
}
NAMED_INDEXES = {
    "simulation_sessions": {
        "ix_simulation_sessions_user_id",
        "ix_simulation_sessions_upload_id",
    },
    "simulation_phases": {"uq_simulation_phases_session_idx"},
    "simulation_personas": {"uq_simulation_personas_session_seat"},
    "simulation_utterances": {
        "uq_simulation_utterances_session_seq",
        "ix_simulation_utterances_session_phase",
    },
    "simulation_persona_library": {"ix_simulation_persona_library_user_id"},
    "simulation_feedback_guidelines": {
        "uq_simulation_feedback_guidelines_version"
    },
}


@pytest.fixture
def engine(tmp_path):
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'm.db'}", poolclass=NullPool
    )

    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    yield eng
    run(eng.dispose())


def _create_app_tables(engine):
    """시뮬레이션 테이블을 뺀 기존 스키마 (기존 DB 흉내)."""

    async def _go():
        tables = [
            t
            for t in Base.metadata.sorted_tables
            if not t.name.startswith("simulation_")
        ]
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(c, tables=tables)
            )

    run(_go())


def _schema(engine):
    async def _go():
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda c: {
                    t: {ix["name"] for ix in inspect(c).get_indexes(t)}
                    for t in inspect(c).get_table_names()
                }
            )

    return run(_go())


def test_empty_db_creates_six_tables_then_is_idempotent(engine):
    assert run(ensure_simulation_tables(engine)) is True
    schema = _schema(engine)
    assert SIM_TABLES <= set(schema)
    for table, names in NAMED_INDEXES.items():
        assert names <= schema[table], table
    assert run(ensure_simulation_tables(engine)) is False


def test_existing_db_keeps_data(engine):
    _create_app_tables(engine)
    maker = async_sessionmaker(engine, class_=AsyncSession)

    async def _seed():
        async with maker() as db:
            user = User(username="t1", nickname="t1")
            db.add(user)
            await db.flush()
            db.add(LessonPlanUpload(user_id=user.id, filename="a.pdf"))
            await db.commit()

    run(_seed())
    assert run(ensure_simulation_tables(engine)) is True

    async def _count():
        async with maker() as db:
            users = await db.scalar(select(func.count(User.id)))
            uploads = await db.scalar(select(func.count(LessonPlanUpload.id)))
            return users, uploads

    assert run(_count()) == (1, 1)


def test_models_match_ddl_columns(engine):
    run(ensure_simulation_tables(engine))

    async def _cols():
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda c: {
                    t: {col["name"] for col in inspect(c).get_columns(t)}
                    for t in SIM_TABLES
                }
            )

    ddl = run(_cols())
    for model in (SimulationSession, SimulationPersona, SimulationUtterance):
        assert {c.name for c in model.__table__.columns} == ddl[
            model.__tablename__
        ]


def test_orm_user_delete_cascades_sim_rows(engine):
    _create_app_tables(engine)
    run(ensure_simulation_tables(engine))
    maker = async_sessionmaker(engine, class_=AsyncSession)

    async def _go():
        async with maker() as db:
            user = User(username="t1", nickname="t1")
            db.add(user)
            await db.flush()
            upload = LessonPlanUpload(user_id=user.id, filename="a.pdf")
            db.add(upload)
            await db.flush()
            sim = SimulationSession(
                user_id=user.id,
                upload_id=upload.id,
                persona_count=1,
                model_name="m",
            )
            db.add(sim)
            await db.flush()
            persona = SimulationPersona(
                session_id=sim.id,
                seat_idx=0,
                display_name="서연",
                color_key="p1",
                source="dataset",
                source_record_id=1,
                raw_profile={},
                adapted_profile={},
                adapted_level="높은 도달",
            )
            db.add(persona)
            await db.flush()
            db.add(
                SimulationUtterance(
                    session_id=sim.id,
                    phase_idx=0,
                    seq=1,
                    speaker_type="student",
                    persona_id=persona.id,
                    content="hi",
                )
            )
            await db.commit()

            await db.delete(user)
            await db.commit()

            counts = []
            for table in (
                "simulation_sessions",
                "simulation_personas",
                "simulation_utterances",
            ):
                counts.append(
                    await db.scalar(text(f"SELECT COUNT(*) FROM {table}"))
                )
            return counts

    assert run(_go()) == [0, 0, 0]
