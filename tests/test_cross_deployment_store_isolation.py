"""
같은 API 키(가짜 클라우드 1개)를 DB 가 다른 두 배포 P·D 가 함께 써도
사용자 스토어가 섞이지 않는다 (#470)

두 DB 의 첫 사용자는 같은 id 를 받는다. 사용자 스토어는 업로드 행의
fs_store_id 로만 검색·삭제하므로 표시 이름(user-{id}-store)이 겹쳐도 된다.
"""

from collections import Counter
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks
from google.genai import errors as genai_errors
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.db import Base
from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from app.routers.auth import logout
from app.services import lessonplan_analysis_service as analysis_mod
from app.services.admin_deletion_service import AdminDeletionService
from app.services.criteria_freshness import ensure_criteria_cache_fresh
from app.services.criteria_vector_service import CriteriaVectorService
from app.services.file_search_service import FileSearchService
from app.services.report_storage_service import ReportStorageService
from app.services.simulation import lessonplan_source
from tests.pdf_samples import text_pdf

NS = SimpleNamespace
REPORT = "".join(f"# {n}. 제목\n본문\n\n" for n in range(1, 6))
QNA_MISSING = (
    "지도안 검색 색인이 없습니다. 지도안을 다시 업로드한 뒤 질문해 주세요."
)
ANALYSIS_MISSING = (
    "지도안 검색 색인이 없습니다. 지도안을 다시 업로드한 뒤 분석해 주세요."
)


class Cloud:
    """메모리 속 File Search + generate_content. P 와 D 가 함께 쓴다."""

    def __init__(self):
        self.stores = {}  # 자원 이름 -> {"display": str, "docs": [표시 이름]}
        self.calls = Counter()
        self.created = 0
        self.searched = []  # generate_content 마다 검색 범위로 잡은 스토어
        self.fail_upload = False
        self.client = NS(
            file_search_stores=NS(
                list=self._list,
                get=self._get,
                create=self._create,
                delete=self._delete,
                upload_to_file_search_store=self._upload,
            ),
            models=NS(generate_content=self._generate),
        )
        self.rubric = self._create({"display_name": "rubric-store"}).name
        self.calls.clear()

    def _list(self, **_):
        self.calls["list"] += 1
        return [
            NS(name=name, display_name=store["display"])
            for name, store in self.stores.items()
        ]

    def _get(self, name, config=None):
        self.calls["get"] += 1
        if name not in self.stores:
            raise genai_errors.ClientError(
                404, {"error": {"code": 404, "status": "NOT_FOUND"}}
            )
        return NS(name=name, display_name=self.stores[name]["display"])

    def _create(self, config):
        self.calls["create"] += 1
        self.created += 1
        name = f"fileSearchStores/s{self.created}"
        self.stores[name] = {"display": config["display_name"], "docs": []}
        return NS(name=name, display_name=config["display_name"])

    def _delete(self, name, config=None):
        self.calls["delete"] += 1
        del self.stores[name]

    def _upload(self, file_search_store_name, file, config):
        if self.fail_upload:
            raise RuntimeError("upload failed")
        self.stores[file_search_store_name]["docs"].append(
            config["display_name"]
        )
        doc = f"{file_search_store_name}/documents/d1"
        return NS(
            done=True,
            error=None,
            response=NS(document_name=doc, parent=file_search_store_name),
        )

    def _generate(self, model=None, contents=None, config=None, **_):
        names = [
            name
            for tool in config.tools or []
            for name in tool.file_search.file_search_store_names
        ]
        self.searched.append(names)
        if names == [self.rubric]:
            text, titles = REPORT, ["rubric.pdf"]
        else:
            titles = [d for n in names for d in self.stores[n]["docs"]]
            text = "원문: " + ", ".join(titles)
        chunks = [
            NS(retrieved_context=NS(title=t, text="x", uri=None))
            for t in titles
        ]
        return NS(
            text=text,
            usage_metadata=None,
            candidates=[
                NS(
                    finish_reason=NS(name="STOP"),
                    grounding_metadata=NS(
                        grounding_chunks=chunks, grounding_supports=None
                    ),
                )
            ],
        )

    def user_stores(self):
        return {
            n: s["docs"] for n, s in self.stores.items() if n != self.rubric
        }


class World:
    def __init__(self, cloud, factories, user_id, admin_id, client):
        self.cloud, self.factories = cloud, factories
        self.user_id, self.admin_id, self.client = user_id, admin_id, client
        self.current = "P"

    def use(self, name):
        self.current = name
        return self

    async def upload(self, name):
        return await self.client.post(
            "/dashboard/upload",
            files={
                "file": (name, BytesIO(text_pdf()), "application/pdf"),
            },
        )

    async def row(self):
        async with self.factories[self.current]() as s:
            return (
                await s.execute(
                    select(LessonPlanUpload)
                    .where(LessonPlanUpload.user_id == self.user_id)
                    .order_by(LessonPlanUpload.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def qna(self):
        row = await self.row()
        return await self.client.post(
            f"/api/qna/{row.fs_document_id or 'none'}",
            json={"question": "학습 목표를 알려 주세요"},
        )

    async def analyze(self):
        return await self.client.post(
            "/api/lessonplan/analyze", json={"session_id": 1}
        )

    async def logout(self):
        """핸들러를 직접 불러 응답과 백그라운드 삭제를 따로 본다 (#247)."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/auth/logout",
                "headers": [],
                "session": {"user_id": self.user_id, "username": "teacher"},
            }
        )
        tasks = BackgroundTasks()
        async with self.factories[self.current]() as s:
            res = await logout(request, tasks, db=s)
        return res, tasks


@pytest_asyncio.fixture
async def world(tmp_path, monkeypatch):
    cloud = Cloud()
    factories, engines = {}, []
    for name in ("P", "D"):
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path}/{name}.db"
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factories[name] = async_sessionmaker(engine, expire_on_commit=False)
        engines.append(engine)
        async with factories[name]() as s:
            users = [
                User(username=u, nickname=u, hashed_password="x", is_admin=a)
                for u, a in (("teacher", False), ("admin", True))
            ]
            s.add_all(users)
            await s.commit()
            ids = [u.id for u in users]
    # 두 DB 의 같은 자리 사용자는 같은 id 다
    w = World(cloud, factories, ids[0], ids[1], None)

    async def override_get_db():
        async with factories[w.current]() as s:
            yield s
            await s.commit()

    async def override_get_user():
        async with factories[w.current]() as s:
            return await s.get(User, w.user_id)

    from app.routers import views as views_mod

    real_path = views_mod.Path
    uploads = tmp_path / "uploads"

    def patched_path(*args, **kwargs):
        p = real_path(*args, **kwargs)
        if str(p) == "app/static/uploads":
            return real_path(str(uploads))
        return p

    monkeypatch.setattr(views_mod, "Path", patched_path)
    monkeypatch.setattr(lessonplan_source, "UPLOADS_DIR", uploads)
    # 관리자 삭제가 실제 체크아웃의 파일을 건드리지 않게 한다
    for name in (
        "LESSONPLAN_BASE_DIR",
        "STATIC_UPLOADS_DIR",
        "SIMULATION_REPORTS_DIR",
    ):
        monkeypatch.setattr(
            f"app.services.admin_deletion_service.{name}",
            str(tmp_path / "isolated" / name),
        )
    monkeypatch.setattr(
        analysis_mod,
        "ReportStorageService",
        lambda: ReportStorageService(base_dir=str(tmp_path / "reports")),
    )
    monkeypatch.setattr(FileSearchService, "_client", cloud.client)
    monkeypatch.setattr("google.genai.Client", lambda *a, **k: cloud.client)
    monkeypatch.setattr(
        CriteriaVectorService,
        "active_stable_id_filter",
        AsyncMock(return_value='stable_id="S1"'),
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[ensure_criteria_cache_fresh] = lambda: None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        w.client = client
        yield w
    for dep in (get_db, get_current_user, ensure_criteria_cache_fresh):
        app.dependency_overrides.pop(dep, None)
    for engine in engines:
        await engine.dispose()


@pytest_asyncio.fixture
async def p_uploaded(world):
    """P 의 사용자가 planP.pdf 를 올린 상태. 반환: P 의 스토어 id."""
    assert (await world.use("P").upload("planP.pdf")).status_code == 303
    store_id = (await world.row()).fs_store_id
    assert world.cloud.user_stores() == {store_id: ["planP.pdf"]}
    world.cloud.calls.clear()
    return store_id


@pytest.mark.asyncio
async def test_logout_without_upload_leaves_the_other_deployment_alone(
    world, p_uploaded
):
    res, tasks = await world.use("D").logout()
    await tasks()

    assert res.status_code == 302
    assert world.cloud.calls["delete"] == 0
    assert world.cloud.calls["list"] == 0
    assert world.cloud.user_stores() == {p_uploaded: ["planP.pdf"]}


@pytest.mark.asyncio
async def test_upload_creates_its_own_store(world, p_uploaded):
    assert (await world.use("D").upload("planD.pdf")).status_code == 303

    d_store = (await world.row()).fs_store_id
    assert d_store != p_uploaded
    assert world.cloud.user_stores() == {
        p_uploaded: ["planP.pdf"],
        d_store: ["planD.pdf"],
    }
    # 표시 이름은 그대로다. 콘솔에서 알아보는 이름표일 뿐이다
    assert {s["display"] for s in world.cloud.stores.values()} == {
        "rubric-store",
        f"user-{world.user_id}-store",
    }
    assert world.cloud.calls["delete"] == 0


@pytest.mark.asyncio
async def test_qna_and_analysis_search_the_store_of_the_own_row(
    world, p_uploaded
):
    await world.use("D").upload("planD.pdf")
    d_store = (await world.row()).fs_store_id

    for name, store_id in (("P", p_uploaded), ("D", d_store)):
        world.use(name)
        world.cloud.calls.clear()
        world.cloud.searched.clear()

        res = await world.qna()
        assert res.status_code == 200, res.text
        assert world.cloud.searched == [[store_id]]
        assert world.cloud.calls["list"] == 0
        assert world.cloud.calls["create"] == 0

        world.cloud.searched.clear()
        res = await world.analyze()
        assert res.status_code == 200, res.text
        # 1패스는 자기 행의 스토어, 2패스는 평가기준 스토어
        assert world.cloud.searched == [[store_id], [world.cloud.rubric]]
        # 분석의 목록 조회는 평가기준 스토어를 찾는 것뿐이라 세지 않는다
        assert world.cloud.calls["create"] == 0


@pytest.mark.asyncio
async def test_admin_user_delete_removes_only_the_own_store(world, p_uploaded):
    await world.use("D").upload("planD.pdf")

    async with world.factories["D"]() as s:
        result = await AdminDeletionService(s).delete_user(
            world.user_id, world.admin_id
        )

    assert result["ok"] is True
    assert world.cloud.user_stores() == {p_uploaded: ["planP.pdf"]}


@pytest.mark.asyncio
async def test_reupload_replaces_the_store_of_the_old_row(world, p_uploaded):
    assert (await world.upload("planP2.pdf")).status_code == 303

    new_store = (await world.row()).fs_store_id
    assert new_store != p_uploaded
    assert world.cloud.user_stores() == {new_store: ["planP2.pdf"]}
    async with world.factories["P"]() as s:
        store_ids = await lessonplan_source.get_store_ids(s, world.user_id)
    assert store_ids == [new_store]


@pytest.mark.asyncio
async def test_failed_document_upload_removes_the_new_store(world):
    world.cloud.fail_upload = True

    res = await world.upload("planP.pdf")

    assert res.status_code == 500
    assert world.cloud.calls["create"] == 1
    assert world.cloud.user_stores() == {}
    assert await world.row() is None


@pytest.mark.asyncio
async def test_failed_row_insert_removes_the_new_store(world):
    with patch(
        "app.routers.views.LessonPlanUpload", side_effect=RuntimeError("db")
    ):
        res = await world.upload("planP.pdf")

    assert res.status_code == 500
    assert world.cloud.user_stores() == {}


@pytest.mark.asyncio
async def test_logout_deletes_the_store_read_before_clearing(world, p_uploaded):
    res, tasks = await world.logout()

    # 응답 시점: 행의 id 는 비었고 스토어는 아직 있다 (#173, #247)
    assert res.status_code == 302
    row = await world.row()
    assert (row.fs_document_id, row.fs_store_id) == (None, None)
    assert world.cloud.user_stores() == {p_uploaded: ["planP.pdf"]}

    await tasks()
    assert world.cloud.user_stores() == {}


@pytest.mark.asyncio
async def test_store_gone_in_cloud_asks_for_reupload(world, p_uploaded):
    del world.cloud.stores[p_uploaded]

    qna = await world.qna()
    analysis = await world.analyze()

    assert (qna.status_code, qna.json()["detail"]) == (404, QNA_MISSING)
    assert (analysis.status_code, analysis.json()["detail"]) == (
        500,
        ANALYSIS_MISSING,
    )
    assert world.cloud.calls["create"] == 0
    assert world.cloud.searched == []
    assert world.cloud.user_stores() == {}


@pytest.mark.asyncio
async def test_row_without_store_id_is_not_indexed(world, p_uploaded):
    async with world.factories["P"]() as s:
        await s.execute(update(LessonPlanUpload).values(fs_store_id=None))
        await s.commit()
    document_id = (await world.row()).fs_document_id

    qna = await world.client.post(
        f"/api/qna/{document_id}", json={"question": "학습 목표"}
    )
    analysis = await world.analyze()
    dashboard = await world.client.get("/dashboard")

    assert (qna.status_code, qna.json()["detail"]) == (404, QNA_MISSING)
    assert (analysis.status_code, analysis.json()["detail"]) == (
        500,
        ANALYSIS_MISSING,
    )
    assert 'aria-label="QnA 챗봇"' not in dashboard.text
    assert world.cloud.calls == Counter()
    assert world.cloud.searched == []
    # 가리키는 행이 없는 스토어는 건드리지 않는다
    assert world.cloud.user_stores() == {p_uploaded: ["planP.pdf"]}
