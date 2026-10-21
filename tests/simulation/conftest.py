"""
시뮬레이션 테스트 공용 하네스 (PLAN 2.4)
임시 파일 SQLite + get_db/get_current_user override + 최소 PDF 업로드.
"""

import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.db import Base, get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from app.services.simulation import lessonplan_source


def minimal_pdf(text: str) -> bytes:
    """ASCII 1쪽 PDF. text에 괄호·역슬래시 금지."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for o in offs:
        out.write(b"%010d 00000 n \n" % o)
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objs) + 1, xref)
    )
    return out.getvalue()


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sim_db(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'sim.db'}", poolclass=NullPool
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    run(_create())
    yield async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    run(engine.dispose())


def _seed_user(sim_db, username, is_admin=False):
    async def _go():
        async with sim_db() as db:
            user = User(username=username, nickname=username, is_admin=is_admin)
            db.add(user)
            await db.commit()
            return user

    return run(_go())


@pytest.fixture
def teacher(sim_db):
    return _seed_user(sim_db, "teacher1")


@pytest.fixture
def other_teacher(sim_db):
    return _seed_user(sim_db, "teacher2")


@pytest.fixture
def admin(sim_db):
    return _seed_user(sim_db, "admin1", is_admin=True)


@pytest.fixture
def client(sim_db, teacher):
    current = {"user": teacher}

    async def _get_db():
        async with sim_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    test_client = TestClient(app)
    test_client.current = current
    yield test_client
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def as_user(client):
    def _switch(user):
        client.current["user"] = user

    return _switch


@pytest.fixture
def make_upload(sim_db, tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    monkeypatch.setattr(lessonplan_source, "UPLOADS_DIR", uploads)

    def _make(user, text="Intro lesson about maps"):
        user_dir = uploads / str(user.id)
        user_dir.mkdir(parents=True, exist_ok=True)
        filename = f"plan_{len(list(user_dir.iterdir()))}.pdf"
        (user_dir / filename).write_bytes(minimal_pdf(text))

        async def _go():
            async with sim_db() as db:
                row = LessonPlanUpload(
                    user_id=user.id,
                    filename=filename,
                    original_filename=filename,
                )
                db.add(row)
                await db.commit()
                return row.id

        return run(_go())

    return _make
