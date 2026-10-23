"""
GET /dashboard가 최근 업로드로 뷰어·QnA·분석 진입점을 복원 (#173, #165)

- 업로드 후 새로고침해도 QnA 챗봇·분석 시작 버튼과 docId가 유지된다
- 업로드가 없거나 File Search 문서 ID가 없는(과거 행·로그아웃) 경우는
  지금처럼 업로드 안내
- 시뮬레이션 피드백의 '지도안으로 돌아가기'(/dashboard)가 같은 화면으로 돌아온다
"""

import base64
import json
from io import BytesIO
from unittest.mock import AsyncMock, patch

import itsdangerous
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import Base
from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from app.services.criteria_freshness import ensure_criteria_cache_fresh
from app.services.simulation import lessonplan_source
from tests.pdf_samples import text_pdf

PDF_BYTES = text_pdf()
QNA_FAB = 'aria-label="QnA 챗봇"'
ANALYSIS_FAB = 'aria-label="분석 시작"'
UPLOAD_HINT = "문서를 업로드하면 분석 및 QnA 기능을 사용할 수 있습니다."


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    uploads = tmp_path / "uploads"
    from app.routers import views as views_mod

    real_path_cls = views_mod.Path

    def _patched_path(*args, **kwargs):
        p = real_path_cls(*args, **kwargs)
        if str(p) == "app/static/uploads":
            return real_path_cls(str(uploads))
        return p

    monkeypatch.setattr(views_mod, "Path", _patched_path)
    monkeypatch.setattr(lessonplan_source, "UPLOADS_DIR", uploads)

    async with factory() as s:
        u = User(username="alice", nickname="alice", hashed_password="x")
        s.add(u)
        await s.commit()
        user_id = u.id

    async def override_get_user():
        async with factory() as s:
            return (
                await s.execute(select(User).where(User.id == user_id))
            ).scalar_one()

    async def override_get_db():
        async with factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[ensure_criteria_cache_fresh] = lambda: None

    fake = {
        "document_id": "fileSearchStores/user1store-abc/documents/doc-1",
        "store_id": "fileSearchStores/user1store-abc",
    }
    with patch("app.routers.views.FileSearchService") as mock_fss:
        inst = mock_fss.return_value
        inst.upload_document = AsyncMock(return_value=fake)
        inst.delete_store_by_display_name = AsyncMock(return_value=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c, factory, user_id, uploads

    for dep in (get_current_user, get_db, ensure_criteria_cache_fresh):
        app.dependency_overrides.pop(dep, None)
    await eng.dispose()


async def _upload(c):
    res = await c.post(
        "/dashboard/upload",
        files={"file": ("plan.pdf", BytesIO(PDF_BYTES), "application/pdf")},
    )
    assert res.status_code == 200
    return res


@pytest.mark.asyncio
async def test_refresh_after_upload_keeps_qna_and_analysis(env):
    c, factory, _, _ = env
    await _upload(c)

    async with factory() as s:
        row = (await s.execute(select(LessonPlanUpload))).scalar_one()
    assert row.fs_document_id.endswith("/documents/doc-1")
    assert row.fs_store_id == "fileSearchStores/user1store-abc"

    res = await c.get("/dashboard")
    assert res.status_code == 200
    html = res.text
    assert QNA_FAB in html
    assert ANALYSIS_FAB in html
    assert 'href="/simulation/setup"' in html
    assert f'const docId = "{row.fs_document_id}"' in html
    assert f'src="/dashboard/uploads/{row.filename}"' in html
    assert "plan.pdf" in html
    assert UPLOAD_HINT not in html
    # 지난 세션·보고서 목록은 문서가 있어도 보인다
    assert 'id="mySessions"' in html
    assert 'id="myReports"' in html


@pytest.mark.asyncio
async def test_no_upload_shows_upload_guidance(env):
    c, *_ = env
    html = (await c.get("/dashboard")).text
    assert UPLOAD_HINT in html
    assert QNA_FAB not in html
    assert ANALYSIS_FAB not in html
    assert 'const docId = ""' in html
    assert "검색 색인이 삭제" not in html


@pytest.mark.asyncio
async def test_legacy_row_without_fs_id_shows_guidance(env):
    c, factory, user_id, uploads = env
    (uploads / str(user_id)).mkdir(parents=True)
    (uploads / str(user_id) / "old.pdf").write_bytes(PDF_BYTES)
    async with factory() as s:
        s.add(
            LessonPlanUpload(
                user_id=user_id, filename="old.pdf", original_filename="old.pdf"
            )
        )
        await s.commit()

    html = (await c.get("/dashboard")).text
    assert UPLOAD_HINT in html
    assert QNA_FAB not in html
    assert "최근 지도안(old.pdf)" in html


@pytest.mark.asyncio
async def test_missing_pdf_file_shows_guidance(env):
    c, factory, user_id, uploads = env
    await _upload(c)
    for f in (uploads / str(user_id)).iterdir():
        f.unlink()

    html = (await c.get("/dashboard")).text
    assert UPLOAD_HINT in html
    assert QNA_FAB not in html


def _session_cookie(data: dict) -> str:
    signer = itsdangerous.TimestampSigner(str(settings.SECRET_KEY))
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


@pytest.mark.asyncio
async def test_logout_deletes_store_and_forgets_fs_ids(env):
    """로그아웃이 user store를 지우면 다음 GET /dashboard는 업로드 안내."""
    c, factory, user_id, _ = env
    await _upload(c)

    c.cookies.set(
        settings.SESSION_COOKIE_NAME,
        _session_cookie({"user_id": user_id, "is_admin": False}),
    )
    with patch(
        "app.services.file_search_service.FileSearchService"
    ) as mock_fss:
        mock_fss.return_value.delete_store_by_display_name = AsyncMock()
        res = await c.post("/auth/logout", follow_redirects=False)
    assert res.status_code == 302
    c.cookies.clear()

    async with factory() as s:
        row = (await s.execute(select(LessonPlanUpload))).scalar_one()
    assert row.fs_document_id is None
    assert row.fs_store_id is None

    html = (await c.get("/dashboard")).text
    assert QNA_FAB not in html
    assert "최근 지도안(plan.pdf)" in html


@pytest.mark.asyncio
async def test_cleanup_forgets_fs_ids(env):
    c, factory, _, _ = env
    await _upload(c)
    res = await c.post("/dashboard/cleanup")
    assert res.json()["status"] == "success"
    async with factory() as s:
        row = (await s.execute(select(LessonPlanUpload))).scalar_one()
    assert row.fs_document_id is None


@pytest.mark.asyncio
async def test_failed_replacement_upload_forgets_deleted_doc(env):
    c, factory, _, _ = env
    await _upload(c)
    from app.routers import views as views_mod

    fss = views_mod.FileSearchService.return_value
    fss.upload_document.side_effect = RuntimeError("upload failed")
    res = await c.post(
        "/dashboard/upload",
        files={"file": ("new.pdf", BytesIO(PDF_BYTES), "application/pdf")},
    )
    assert res.status_code == 500
    assert fss.delete_store_by_display_name.await_count == 2

    async with factory() as s:
        row = (await s.execute(select(LessonPlanUpload))).scalar_one()
    assert row.fs_document_id is None
    html = (await c.get("/dashboard")).text
    assert UPLOAD_HINT in html
    assert QNA_FAB not in html
    assert "최근 지도안(plan.pdf)" in html


def test_sim_feedback_back_button_goes_to_dashboard():
    """#165: 버튼 이름은 유지하고 /dashboard가 최근 지도안을 다시 보여 준다."""
    from pathlib import Path

    html = Path("app/templates/user/simulation_feedback.html").read_text()
    assert 'href="/dashboard"' in html
    assert "지도안으로 돌아가기" in html


@pytest.mark.asyncio
async def test_fs_id_migration_adds_columns(tmp_path):
    from sqlalchemy import inspect, text

    from app.migrations import ensure_lessonplan_uploads_fs_id_columns

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/m.db")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE lessonplan_uploads ("
                "id INTEGER PRIMARY KEY, user_id INTEGER, filename TEXT)"
            )
        )
    assert await ensure_lessonplan_uploads_fs_id_columns(engine) is True
    assert await ensure_lessonplan_uploads_fs_id_columns(engine) is False
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {
                x["name"] for x in inspect(c).get_columns("lessonplan_uploads")
            }
        )
    assert {"fs_document_id", "fs_store_id"} <= cols
    await engine.dispose()
