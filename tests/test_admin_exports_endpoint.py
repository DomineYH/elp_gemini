# tests/test_admin_exports_endpoint.py
import io
import json
import os
import zipfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies import get_current_admin
from app.main import app
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.users import User


# ----- fixtures -----

_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = async_sessionmaker(
    _engine, class_=AsyncSession, expire_on_commit=False
)

_admin = User(
    id=999,
    username="export_admin",
    nickname="ExportAdmin",
    hashed_password="hashed",
    is_admin=True,
)


async def _override_get_db():
    async with _TestSession() as session:
        yield session


def _override_admin():
    return _admin


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_admin] = _override_admin
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session():
    async with _TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def client_admin():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def client_unauth():
    # Remove admin override so auth fails, then restore after test
    saved = app.dependency_overrides.pop(get_current_admin, None)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client
    # Restore admin override for subsequent tests
    if saved is not None:
        app.dependency_overrides[get_current_admin] = saved


# ----- tests -----


@pytest.mark.asyncio
async def test_export_requires_admin(client_unauth):
    resp = await client_unauth.get("/admin/api/exports/all.zip")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_export_returns_valid_zip(client_admin, db_session, tmp_path):
    user = User(id=42, username="u42", nickname="kim")
    db_session.add(user)
    report_md = tmp_path / "report.md"
    report_md.write_text("# Report\nHello", encoding="utf-8")
    db_session.add(AnalysisReport(
        user_id=42,
        lessonplan_filename="42_lp.pdf",
        lessonplan_original_name="1학년_수업지도안.pdf",
        report_filename="42_lp_reports.md",
        report_path=str(report_md),
    ))
    s = ChatSession(user_id=42, title="t1")
    db_session.add(s)
    await db_session.flush()
    db_session.add_all([
        ChatMessage(
            session_id=s.id, role=MessageRole.USER, content="안녕"
        ),
        ChatMessage(
            session_id=s.id,
            role=MessageRole.ASSISTANT,
            content="hello",
        ),
    ])
    await db_session.commit()

    resp = await client_admin.get("/admin/api/exports/all.zip")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert "manifest.csv" in names
    assert "users.csv" in names
    assert "README.txt" in names
    convo = [n for n in names if n.startswith("conversations/")][0]
    lines = zf.read(convo).decode("utf-8").splitlines()
    parsed = [json.loads(l) for l in lines]
    assert len(parsed) == 2
    assert parsed[0]["role"] == "user"


@pytest.mark.asyncio
async def test_export_invalid_date_returns_400(client_admin):
    resp = await client_admin.get(
        "/admin/api/exports/all.zip?date_from=2026-99-01"
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_export_missing_report_file_marks_in_manifest(
    client_admin, db_session
):
    """원본 보고서 .md 파일이 사라진 경우 manifest에 MISSING으로 표시."""
    db_session.add(User(id=1, username="t", nickname="t"))
    db_session.add(AnalysisReport(
        user_id=1,
        lessonplan_filename="does_not_exist.pdf",
        lessonplan_original_name="missing.pdf",
        report_filename="x.md",
        report_path="/no/such/path.md",
    ))
    await db_session.commit()

    resp = await client_admin.get("/admin/api/exports/all.zip")
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    manifest = zf.read("manifest.csv").decode("utf-8")
    assert "MISSING" in manifest


@pytest.mark.asyncio
async def test_export_include_meta_only_skips_data_dirs(
    client_admin, db_session
):
    db_session.add(User(id=1, username="t", nickname="t"))
    db_session.add(AnalysisReport(
        user_id=1,
        lessonplan_filename="1_lp.pdf",
        lessonplan_original_name="lp.pdf",
        report_filename="1_lp_reports.md",
        report_path="/tmp/lp.md",
    ))
    await db_session.commit()

    resp = await client_admin.get(
        "/admin/api/exports/all.zip?include=meta"
    )
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert "manifest.csv" in names
    assert "users.csv" in names
    assert "README.txt" in names
    assert not any(n.startswith("reports/") for n in names)
    assert not any(n.startswith("conversations/") for n in names)
    assert not any(n.startswith("lessonplans/") for n in names)
