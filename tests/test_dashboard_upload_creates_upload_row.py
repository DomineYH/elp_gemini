"""
/dashboard/upload 이 LessonPlanUpload 행을 만드는지 검증.
"""
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "t.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    yield factory
    await eng.dispose()


@pytest_asyncio.fixture
async def client(session_factory, tmp_path, monkeypatch):
    # Redirect static/uploads writes to a tmp dir to avoid polluting repo
    from app.routers import views as views_mod
    real_path_cls = views_mod.Path

    def _patched_path(*args, **kwargs):
        p = real_path_cls(*args, **kwargs)
        if str(p) == "app/static/uploads":
            return real_path_cls(str(tmp_path / "uploads"))
        return p

    monkeypatch.setattr(views_mod, "Path", _patched_path)

    # Stub FileSearchService — we're testing the DB-row side effect, not the
    # real Google call
    fake_result = {"document_id": "doc-1", "store_id": "store-1"}
    with patch(
        "app.routers.views.FileSearchService"
    ) as mock_fss:
        instance = mock_fss.return_value
        instance.upload_document = AsyncMock(return_value=fake_result)
        instance.delete_store_by_display_name = AsyncMock(return_value=None)

        async with session_factory() as s:
            u = User(
                username="alice", nickname="alice",
                email="a@a.com", hashed_password="x",
            )
            s.add(u)
            await s.commit()
            user_id = u.id

        async def override_get_user():
            async with session_factory() as s:
                return (
                    await s.execute(
                        select(User).where(User.id == user_id)
                    )
                ).scalar_one()

        async def override_get_db():
            async with session_factory() as s:
                yield s
                await s.commit()

        app.dependency_overrides[get_current_user] = override_get_user
        app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as c:
            yield c, session_factory

        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_dashboard_upload_inserts_lessonplan_upload_row(client):
    c, session_factory = client
    pdf_bytes = (
        b"%PDF-1.4\n%fake pdf for test\n"
        b"1 0 obj\n<<>>\nendobj\n%%EOF\n"
    )
    files = {"file": ("plan.pdf", BytesIO(pdf_bytes), "application/pdf")}

    # Patching PdfReader because the fake bytes aren't a real PDF — we don't
    # care about text extraction for this test
    with patch("app.routers.views.PdfReader") as mock_reader:
        instance = mock_reader.return_value
        instance.pages = []  # extract_text loop becomes a no-op
        res = await c.post("/dashboard/upload", files=files)

    # The endpoint renders the dashboard template back; status will be 200
    assert res.status_code == 200

    async with session_factory() as s:
        rows = (
            await s.execute(select(LessonPlanUpload))
        ).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.original_filename == "plan.pdf"
        assert row.file_hash is not None
        assert len(row.file_hash) == 64
        # filename should contain user + original (timestamped form)
        assert "plan.pdf" in row.filename
        assert "alice" in row.filename


@pytest.mark.asyncio
async def test_dashboard_upload_rejects_file_over_limit(
    client, monkeypatch
):
    c, session_factory = client

    from app.routers import views as views_mod

    monkeypatch.setattr(views_mod, "DASHBOARD_MAX_UPLOAD_SIZE", 8)
    files = {
        "file": (
            "plan.pdf",
            BytesIO(b"%PDF-1.4\nlarger-than-limit"),
            "application/pdf",
        )
    }

    with patch("app.routers.views.PdfReader") as mock_reader:
        res = await c.post("/dashboard/upload", files=files)

    assert res.status_code == 400
    assert "파일 크기는" in res.text
    mock_reader.assert_not_called()

    async with session_factory() as s:
        rows = (
            await s.execute(select(LessonPlanUpload))
        ).scalars().all()
        assert rows == []
