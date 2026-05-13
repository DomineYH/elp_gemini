"""Upload 라우터가 lessonplan_uploads 행을 만들고 upload_id 를 반환하는지 검증."""
import pytest
import pytest_asyncio
from io import BytesIO
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import app
from app.dependencies import get_current_user, get_db
from app.db import Base
from app.models.users import User
from app.models.lessonplan_uploads import LessonPlanUpload


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
    # Storage writes to a tmp dir so the test doesn't pollute repo data/
    monkeypatch.setenv("PYTEST_TMP_LESSONPLAN_DIR", str(tmp_path / "lp"))

    # Stub LessonPlanStorageService to use tmp dir
    from app.services import lessonplan_storage_service as svc_mod
    original_init = svc_mod.LessonPlanStorageService.__init__

    def patched_init(self, base_dir=None):
        original_init(self, base_dir=str(tmp_path / "lp"))

    monkeypatch.setattr(
        svc_mod.LessonPlanStorageService,
        "__init__",
        patched_init,
    )

    # Seed a user
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
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, session_factory

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_upload_creates_lessonplan_upload_row(client):
    c, session_factory = client
    pdf_bytes = (
        b"%PDF-1.4\n%fake pdf for test\n"
        b"1 0 obj\n<<>>\nendobj\n%%EOF\n"
    )
    files = {"file": ("plan.pdf", BytesIO(pdf_bytes), "application/pdf")}

    res = await c.post("/api/lessonplans/upload", files=files)

    assert res.status_code == 201
    body = res.json()
    assert "upload_id" in body
    assert isinstance(body["upload_id"], int)
    assert body["upload_id"] > 0

    async with session_factory() as s:
        rows = (
            await s.execute(select(LessonPlanUpload))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == body["upload_id"]
        assert rows[0].original_filename == "plan.pdf"
        assert rows[0].file_hash is not None
        assert len(rows[0].file_hash) == 64


@pytest.mark.asyncio
async def test_two_uploads_same_filename_produce_two_rows(client):
    c, session_factory = client
    pdf_bytes = b"%PDF-1.4\nfake\n%%EOF\n"
    files1 = {"file": ("plan.pdf", BytesIO(pdf_bytes), "application/pdf")}
    files2 = {"file": ("plan.pdf", BytesIO(pdf_bytes), "application/pdf")}

    r1 = await c.post("/api/lessonplans/upload", files=files1)
    r2 = await c.post("/api/lessonplans/upload", files=files2)

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["upload_id"] != r2.json()["upload_id"]

    async with session_factory() as s:
        rows = (
            await s.execute(select(LessonPlanUpload))
        ).scalars().all()
        assert len(rows) == 2
