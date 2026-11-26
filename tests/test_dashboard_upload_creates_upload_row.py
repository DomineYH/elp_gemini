"""
/dashboard/upload 이 LessonPlanUpload 행을 만드는지 검증.
"""

import asyncio
import re
import threading
import time
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db import Base
from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from tests.pdf_samples import blank_pdf, image_only_pdf, text_pdf


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
    with patch("app.routers.views.FileSearchService") as mock_fss:
        instance = mock_fss.return_value
        instance.upload_document = AsyncMock(return_value=fake_result)
        instance.delete_store_by_display_name = AsyncMock(return_value=None)

        async with session_factory() as s:
            u = User(
                username="alice",
                nickname="alice",
                hashed_password="x",
            )
            s.add(u)
            await s.commit()
            user_id = u.id

        async def override_get_user():
            async with session_factory() as s:
                return (
                    await s.execute(select(User).where(User.id == user_id))
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
    files = {"file": ("plan.pdf", BytesIO(text_pdf()), "application/pdf")}

    res = await c.post("/dashboard/upload", files=files)

    # PRG: 성공하면 /dashboard 로 303 (#266)
    assert res.status_code == 303
    assert res.headers["location"] == "/dashboard"

    async with session_factory() as s:
        rows = (await s.execute(select(LessonPlanUpload))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.original_filename == "plan.pdf"
        assert row.file_hash is not None
        assert len(row.file_hash) == 64
        # filename is "{YYYYMMDDHHMMSSffffff}_{original}"; user is the directory
        assert re.fullmatch(r"\d{20}_plan\.pdf", row.filename)

    # 리다이렉트 전에 commit 되어 이어진 GET 이 업로드를 본다
    follow = await c.get("/dashboard")
    assert follow.status_code == 200
    assert "plan.pdf" in follow.text


@pytest.mark.asyncio
async def test_get_dashboard_upload_redirects_to_dashboard(client):
    c, _ = client

    res = await c.get("/dashboard/upload")

    assert res.status_code == 303
    assert res.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_dashboard_upload_rejects_file_over_limit(client, monkeypatch):
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

    with patch("app.routers.views.extract_pdf_text") as mock_reader:
        res = await c.post("/dashboard/upload", files=files)

    assert res.status_code == 400
    assert "파일 크기는" in res.text
    mock_reader.assert_not_called()

    async with session_factory() as s:
        rows = (await s.execute(select(LessonPlanUpload))).scalars().all()
        assert rows == []


def _uploaded_files(tmp_path):
    return [p for p in (tmp_path / "uploads").rglob("*") if p.is_file()]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [b"", b"not a pdf", b"%PDF-1.4\ntruncated"],
    ids=["empty", "no-signature", "corrupt"],
)
async def test_dashboard_upload_rejects_bad_pdf(client, tmp_path, payload):
    c, session_factory = client
    files = {"file": ("bad.pdf", BytesIO(payload), "application/pdf")}

    res = await c.post("/dashboard/upload", files=files)

    assert res.status_code == 400
    assert "손상되었거나 비어" in res.text
    assert _uploaded_files(tmp_path) == []
    async with session_factory() as s:
        rows = (await s.execute(select(LessonPlanUpload))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_dashboard_upload_failure_removes_file_and_hides_error(
    client, tmp_path
):
    c, _ = client
    files = {"file": ("plan.pdf", BytesIO(text_pdf()), "application/pdf")}

    with patch("app.routers.views.FileSearchService") as mock_fss:
        mock_fss.return_value.delete_store_by_display_name = AsyncMock()
        mock_fss.return_value.upload_document = AsyncMock(
            side_effect=RuntimeError("secret internal detail")
        )
        res = await c.post("/dashboard/upload", files=files)

    assert res.status_code == 500
    assert "secret internal detail" not in res.text
    assert _uploaded_files(tmp_path) == []


@pytest.mark.asyncio
async def test_dashboard_upload_failure_after_flush_rolls_back_row(
    client, tmp_path
):
    # get_db 는 정상 반환을 commit 하므로 실패 시 flush 된 행도 남으면 안 된다.
    c, session_factory = client
    files = {"file": ("plan.pdf", BytesIO(text_pdf()), "application/pdf")}

    # 업로드 행을 담은 첫 commit(리다이렉트 직전)만 실패시키고 나머지는 실제로 돈다
    real_commit = AsyncSession.commit
    failed = []

    async def flaky_commit(self):
        has_upload = any(
            isinstance(o, LessonPlanUpload) for o in self.identity_map.values()
        )
        if has_upload and not failed:
            failed.append(1)
            raise RuntimeError("boom")
        await real_commit(self)

    with patch.object(AsyncSession, "commit", flaky_commit):
        res = await c.post("/dashboard/upload", files=files)

    assert failed
    assert res.status_code == 500
    assert _uploaded_files(tmp_path) == []
    async with session_factory() as s:
        rows = (await s.execute(select(LessonPlanUpload))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [blank_pdf(), image_only_pdf()], ids=["blank", "image-only"]
)
async def test_dashboard_upload_rejects_textless_pdf_before_store_delete(
    client, tmp_path, payload
):
    # 기존 지도안 스토어를 지우기 전에 거부해야 한다 (#249)
    c, session_factory = client
    files = {"file": ("scan.pdf", BytesIO(payload), "application/pdf")}

    with patch("app.routers.views.FileSearchService") as mock_fss:
        mock_fss.return_value.delete_store_by_display_name = AsyncMock()
        mock_fss.return_value.upload_document = AsyncMock()
        res = await c.post("/dashboard/upload", files=files)

    assert res.status_code == 400
    assert "이미지(스캔)로만 된 PDF는 올릴 수 없습니다." in res.text
    mock_fss.return_value.delete_store_by_display_name.assert_not_called()
    mock_fss.return_value.upload_document.assert_not_called()
    assert _uploaded_files(tmp_path) == []
    async with session_factory() as s:
        rows = (await s.execute(select(LessonPlanUpload))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_dashboard_upload_extracts_off_event_loop_thread(client):
    # 추출이 루프 스레드에서 돌면 그동안 서버 전체가 멈춘다 (#453)
    c, session_factory = client
    from app.routers import views as views_mod

    real = views_mod.extract_pdf_text
    seen = []

    def recording(source):
        seen.append(threading.get_ident())
        return real(source)

    files = {"file": ("plan.pdf", BytesIO(text_pdf()), "application/pdf")}
    with patch("app.routers.views.extract_pdf_text", recording):
        res = await c.post("/dashboard/upload", files=files)

    assert res.status_code == 303
    assert len(seen) == 1
    assert seen[0] != threading.get_ident()
    async with session_factory() as s:
        rows = (await s.execute(select(LessonPlanUpload))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_dashboard_upload_keeps_event_loop_responsive(client):
    # 추출이 0.3초 막는 동안에도 10ms 간격 코루틴이 제때 깨어난다 (#453)
    c, _ = client

    def slow(source):
        time.sleep(0.3)
        return "x" * 40

    gaps = []

    async def ticker():
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    files = {"file": ("plan.pdf", BytesIO(text_pdf()), "application/pdf")}
    with patch("app.routers.views.extract_pdf_text", slow):
        task = asyncio.create_task(ticker())
        try:
            res = await c.post("/dashboard/upload", files=files)
        finally:
            task.cancel()

    assert res.status_code == 303
    # 10ms 대기를 뺀 지연이 0.15초 미만 (루프에서 돌면 약 0.3초)
    assert max(gaps) - 0.01 < 0.15


@pytest.mark.asyncio
async def test_concurrent_same_name_upload_keeps_first_file(
    client, tmp_path, monkeypatch
):
    # 같은 초·같은 이름의 두 번째 업로드가 첫 요청의 파일을 지우면 안 된다 (#453)
    from datetime import datetime as real_datetime

    from app.routers import views as views_mod

    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 0, 0, 0, next(micros))

    micros = iter(range(1, 100))
    monkeypatch.setattr(views_mod, "datetime", FrozenDatetime)

    real = views_mod.extract_pdf_text
    started = threading.Event()
    release = threading.Event()
    calls = []

    def extract(source):
        calls.append(source)
        result = real(source)
        if len(calls) == 1:
            started.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(views_mod, "extract_pdf_text", extract)
    c, session_factory = client
    first = asyncio.create_task(
        c.post(
            "/dashboard/upload",
            files={
                "file": ("same.pdf", BytesIO(text_pdf()), "application/pdf")
            },
        )
    )
    try:
        for _ in range(500):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        second = await c.post(
            "/dashboard/upload",
            files={
                "file": ("same.pdf", BytesIO(blank_pdf()), "application/pdf")
            },
        )
        assert second.status_code == 400
    finally:
        release.set()
    assert (await first).status_code == 303

    async with session_factory() as s:
        rows = (await s.execute(select(LessonPlanUpload))).scalars().all()
    assert len(rows) == 1
    stored = tmp_path / "uploads" / str(rows[0].user_id) / rows[0].filename
    assert stored.exists()
