"""
수업 시뮬레이션 테이블 6개 idempotent 생성 (ADR 0001).

라이브러리·피드백 지침 테이블도 여기서 만든다(모델은 후속 티켓).
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# (테이블, CREATE TABLE, [(인덱스 이름, CREATE INDEX)]) — FK 순서대로
_TABLES = [
    (
        "simulation_sessions",
        """
        CREATE TABLE simulation_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            upload_id INTEGER NOT NULL
                REFERENCES lessonplan_uploads(id) ON DELETE CASCADE,
            status VARCHAR(16) NOT NULL DEFAULT 'running',
            current_phase_idx INTEGER NOT NULL DEFAULT 0,
            persona_count INTEGER NOT NULL,
            model_name VARCHAR(100) NOT NULL,
            feedback_json JSON,
            feedback_report_path VARCHAR(1000),
            feedback_guideline_version INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME
        )
        """,
        [
            (
                "ix_simulation_sessions_user_id",
                "CREATE INDEX ix_simulation_sessions_user_id "
                "ON simulation_sessions(user_id)",
            ),
            (
                "ix_simulation_sessions_upload_id",
                "CREATE INDEX ix_simulation_sessions_upload_id "
                "ON simulation_sessions(upload_id)",
            ),
        ],
    ),
    (
        "simulation_phases",
        """
        CREATE TABLE simulation_phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL
                REFERENCES simulation_sessions(id) ON DELETE CASCADE,
            idx INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            minutes INTEGER,
            teacher_prompt TEXT NOT NULL DEFAULT '',
            task TEXT NOT NULL DEFAULT '',
            materials TEXT NOT NULL DEFAULT '',
            cautions TEXT NOT NULL DEFAULT '',
            source_span TEXT NOT NULL DEFAULT ''
        )
        """,
        [
            (
                "uq_simulation_phases_session_idx",
                "CREATE UNIQUE INDEX uq_simulation_phases_session_idx "
                "ON simulation_phases(session_id, idx)",
            ),
        ],
    ),
    (
        "simulation_personas",
        """
        CREATE TABLE simulation_personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL
                REFERENCES simulation_sessions(id) ON DELETE CASCADE,
            seat_idx INTEGER NOT NULL,
            display_name VARCHAR(20) NOT NULL,
            color_key VARCHAR(4) NOT NULL,
            source VARCHAR(16) NOT NULL,
            source_record_id INTEGER NOT NULL,
            raw_profile JSON NOT NULL,
            adapted_profile JSON NOT NULL,
            adapted_level VARCHAR(20) NOT NULL
        )
        """,
        [
            (
                "uq_simulation_personas_session_seat",
                "CREATE UNIQUE INDEX uq_simulation_personas_session_seat "
                "ON simulation_personas(session_id, seat_idx)",
            ),
        ],
    ),
    (
        "simulation_utterances",
        """
        CREATE TABLE simulation_utterances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL
                REFERENCES simulation_sessions(id) ON DELETE CASCADE,
            phase_idx INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            speaker_type VARCHAR(10) NOT NULL,
            persona_id INTEGER
                REFERENCES simulation_personas(id) ON DELETE CASCADE,
            target_persona_id INTEGER
                REFERENCES simulation_personas(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            structured JSON,
            model_name VARCHAR(100),
            temperature REAL,
            latency_ms INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        [
            (
                "uq_simulation_utterances_session_seq",
                "CREATE UNIQUE INDEX uq_simulation_utterances_session_seq "
                "ON simulation_utterances(session_id, seq)",
            ),
            (
                "ix_simulation_utterances_session_phase",
                "CREATE INDEX ix_simulation_utterances_session_phase "
                "ON simulation_utterances(session_id, phase_idx)",
            ),
        ],
    ),
    (
        "simulation_persona_library",
        """
        CREATE TABLE simulation_persona_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            raw_profile JSON NOT NULL,
            adapted_profile JSON NOT NULL,
            adapted_level VARCHAR(20) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        [
            (
                "ix_simulation_persona_library_user_id",
                "CREATE INDEX ix_simulation_persona_library_user_id "
                "ON simulation_persona_library(user_id)",
            ),
        ],
    ),
    (
        "simulation_feedback_guidelines",
        """
        CREATE TABLE simulation_feedback_guidelines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 0,
            required_aspects JSON NOT NULL,
            criteria_ids JSON NOT NULL,
            extra_instructions TEXT NOT NULL DEFAULT '',
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        [
            (
                "uq_simulation_feedback_guidelines_version",
                "CREATE UNIQUE INDEX "
                "uq_simulation_feedback_guidelines_version "
                "ON simulation_feedback_guidelines(version)",
            ),
        ],
    ),
]


def _collect_schema(sync_conn) -> dict[str, set[str]]:
    inspector = inspect(sync_conn)
    return {
        t: {ix["name"] for ix in inspector.get_indexes(t)}
        for t in inspector.get_table_names()
    }


async def ensure_simulation_tables(engine: AsyncEngine) -> bool:
    """
    없는 테이블·인덱스만 만든다.

    Returns:
        하나라도 만들었으면 True, 모두 있으면 False
    """
    async with engine.begin() as conn:
        schema = await conn.run_sync(_collect_schema)
        changed = False
        for table, ddl, indexes in _TABLES:
            if table not in schema:
                await conn.execute(text(ddl))
                logger.info("%s 테이블 생성", table)
                changed = True
            existing = schema.get(table, set())
            for name, index_ddl in indexes:
                if name not in existing:
                    await conn.execute(text(index_ddl))
                    changed = True
        return changed
