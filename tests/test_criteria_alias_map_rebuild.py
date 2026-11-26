"""#471: 못 읽는 alias_map을 DB 캐시로 다시 쓰는 복구.

진짜: CriteriaReconciliationService, CriteriaAliasMapService(fetch/replace),
repository 둘, 메모리 SQLite. 가짜: File Search 클라이언트(외부 호출 0회).
"""

import asyncio
import base64
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.repositories.app_state_repository import (
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    AppStateRepository,
)
from app.repositories.criteria_repository import CriteriaRepository
from app.schemas.alias_map import AliasMap
from app.services.alias_map_codec import (
    decode_alias_map_payload,
    encode_alias_map_payload,
)
from app.services.criteria_alias_map_service import CriteriaAliasMapService
from app.services.criteria_reconciliation_service import (
    CriteriaReconciliationService,
    ReconcileResult,
)
from app.services.criteria_vector_service import CriteriaVectorService

STORE = "rubric-store"
RUBRIC = "fileSearchStores/rubric"
A_AT = "2026-11-01T00:00:00Z"
BASE = {
    "A": {"alias": "기준 A", "status": "active", "activated_at": A_AT},
    "B": {"alias": "기준 B", "status": "uploaded", "activated_at": None},
}


def _payload(entries, **extra):
    return {
        "schema_version": 1,
        "updated_at": "2026-11-25T07:09:39.375327Z",
        "entries": entries,
        **extra,
    }


class FakeCloud:
    """rubric 스토어 하나: 기준 문서(stable_id)와 alias_map 문서."""

    def __init__(self):
        self.file_search_stores = SimpleNamespace(
            list=lambda **k: [SimpleNamespace(display_name=STORE, name=RUBRIC)],
            upload_to_file_search_store=self._upload,
            documents=SimpleNamespace(list=self._docs, delete=self._delete),
        )
        self.criteria = list(BASE)
        self.alias_docs = {
            f"{RUBRIC}/documents/aliasmap": encode_alias_map_payload(
                _payload(BASE)
            )
        }
        self.writes: list[str] = []
        self.delete_fails = 0
        self._seq = 0

    def _docs(self, parent=None, **k):
        docs = [
            SimpleNamespace(
                name=f"{RUBRIC}/documents/{sid.lower()}",
                display_name=f"{sid}.pdf",
                custom_metadata=[
                    {"key": "type", "string_value": "criteria"},
                    {"key": "stable_id", "string_value": sid},
                    {
                        "key": "original_title_b64",
                        "string_value": base64.b64encode(
                            f"{sid}.pdf".encode()
                        ).decode(),
                    },
                ],
            )
            for sid in self.criteria
        ]
        return docs + [
            SimpleNamespace(
                name=name,
                display_name="alias-map",
                custom_metadata=[
                    {"key": "type", "string_value": "alias_map"},
                    {
                        "key": "payload_b64",
                        "string_list_value": {"values": chunks},
                    },
                ],
            )
            for name, chunks in self.alias_docs.items()
        ]

    def _upload(self, file_search_store_name=None, file=None, config=None):
        self._seq += 1
        name = f"{RUBRIC}/documents/aliasmap-new{self._seq}"
        meta = {m["key"]: m for m in config["custom_metadata"]}
        self.alias_docs[name] = meta["payload_b64"]["string_list_value"][
            "values"
        ]
        self.writes.append(f"upload {name}")
        return SimpleNamespace(
            done=True, error=None, response=SimpleNamespace(document_name=name)
        )

    def _delete(self, name=None, config=None):
        self.writes.append(f"delete {name}")
        if self.delete_fails:
            self.delete_fails -= 1
            raise RuntimeError("삭제 실패(가짜)")
        self.alias_docs.pop(name)

    # --- 테스트가 쓰는 것 ---
    def break_map(self, kind):
        name = next(iter(self.alias_docs))
        entries = decode_alias_map_payload(self.alias_docs[name])["entries"]
        if kind == "garbage":
            chunks = ["!!!깨진 payload"]
        elif kind == "v2":
            chunks = encode_alias_map_payload(
                _payload(entries, schema_version=2)
            )
        elif kind == "extra":
            chunks = encode_alias_map_payload(_payload(entries, note="x"))
        else:  # empty
            chunks = []
        self.alias_docs[name] = chunks

    def valid_maps(self) -> list[AliasMap]:
        """모든 alias_map 문서를 엄격하게 읽는다(못 읽으면 예외)."""
        return [
            AliasMap.model_validate(decode_alias_map_payload(chunks))
            for chunks in self.alias_docs.values()
        ]


async def _keep_loop_awake():
    while True:
        await asyncio.sleep(0.01)


@asynccontextmanager
async def _world():
    """(cloud, session_factory, make_service)를 준다. 캐시는 정상 클라우드로 채워 둔다."""
    from app.db import Base
    from app.models import app_state as _a  # noqa: F401
    from app.models import criteria as _c  # noqa: F401

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ticker = asyncio.create_task(_keep_loop_awake())
    cloud = FakeCloud()

    def make(db):
        vec = MagicMock()
        vec.file_search_service.client = cloud
        vec.list_criteria_documents = (
            lambda: CriteriaVectorService.list_criteria_documents(
                SimpleNamespace(
                    file_search_service=SimpleNamespace(client=cloud),
                    store_name=STORE,
                )
            )
        )
        return CriteriaReconciliationService(
            db=db,
            vector_service=vec,
            alias_map_service=CriteriaAliasMapService(
                client=cloud, store_display_name=STORE
            ),
            criteria_repo=CriteriaRepository(db=db),
            app_state_repo=AppStateRepository(db=db),
        )

    async def run(**kwargs) -> ReconcileResult:
        async with factory() as db:
            result = await make(db).reconcile(**kwargs)
            await db.commit()
        return result

    async def state():
        async with factory() as db:
            repo = AppStateRepository(db=db)
            return await repo.get(KEY_SYNC_STATE), await repo.get(
                KEY_SYNC_ERROR
            )

    async def cache():
        async with factory() as db:
            rows = await CriteriaRepository(db=db).get_all_criteria()
            return {r.stable_id: (r.display_alias, r.status) for r in rows}

    async def clear_cache():
        async with factory() as db:
            await CriteriaRepository(db=db).delete_by_stable_ids_except(set())
            await db.commit()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        with patch(
            "app.services.criteria_reconciliation_service.sha256_hex_of_api_key",
            return_value="samehash",
        ):
            assert (await run()).ok
            cloud.writes.clear()
            yield SimpleNamespace(
                cloud=cloud,
                run=run,
                state=state,
                cache=cache,
                clear_cache=clear_cache,
            )
    finally:
        await engine.dispose()
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker


async def _active_filter(cloud):
    return await CriteriaVectorService.active_stable_id_filter(cloud, STORE)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["garbage", "v2", "extra", "empty"])
async def test_rebuild_restores_alias_map_from_cache(kind):
    async with _world() as w:
        w.cloud.break_map(kind)

        result = await w.run(rebuild_alias_map_from_cache=True)

        assert result.ok is True
        (alias_map,) = w.cloud.valid_maps()  # 유효한 문서 1개만 남는다
        assert alias_map.model_dump()["entries"] == BASE
        assert await w.state() == ("ok", None)
        assert await _active_filter(w.cloud) == 'stable_id="A"'
        assert await w.cache() == {
            "A": ("기준 A", "active"),
            "B": ("기준 B", "uploaded"),
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("absent", [False, True])
async def test_rebuild_is_refused_without_writes_when_map_is_fine_or_absent(
    absent,
):
    async with _world() as w:
        if absent:
            w.cloud.alias_docs.clear()

        result = await w.run(rebuild_alias_map_from_cache=True)

        assert (result.ok, result.skipped) == (False, True)
        assert w.cloud.writes == []
        assert await w.state() == ("ok", None)


@pytest.mark.asyncio
async def test_rebuild_deletes_every_unreadable_document():
    async with _world() as w:
        w.cloud.break_map("garbage")
        w.cloud.alias_docs[f"{RUBRIC}/documents/aliasmap-dup"] = ["???"]

        result = await w.run(rebuild_alias_map_from_cache=True)

        assert result.ok is True
        assert len(w.cloud.valid_maps()) == 1
        assert (await w.state())[0] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["garbage", "v2"])
async def test_rebuild_delete_failure_marks_needs_resync_and_retry_works(kind):
    async with _world() as w:
        w.cloud.break_map(kind)
        w.cloud.delete_fails = 1

        failed = await w.run(rebuild_alias_map_from_cache=True)

        assert failed.ok is False and failed.error
        assert (await w.state())[0] == "needs_resync"

        retried = await w.run(rebuild_alias_map_from_cache=True)

        assert retried.ok is True
        assert await w.state() == ("ok", None)
        assert await _active_filter(w.cloud) == 'stable_id="A"'
        # 첫 시도가 올린 문서는 다음 조회(fetch)가 치운다
        assert len(w.cloud.valid_maps()) == 1


@pytest.mark.asyncio
async def test_rebuild_adds_cloud_only_criteria_as_inactive():
    async with _world() as w:
        w.cloud.criteria.append("C")
        w.cloud.break_map("garbage")

        assert (await w.run(rebuild_alias_map_from_cache=True)).ok

        (alias_map,) = w.cloud.valid_maps()
        assert alias_map.entries["C"].model_dump() == {
            "alias": None,
            "status": "uploaded",
            "activated_at": None,
        }
        assert await _active_filter(w.cloud) == 'stable_id="A"'


@pytest.mark.asyncio
async def test_rebuild_drops_cached_criteria_whose_document_is_gone():
    async with _world() as w:
        w.cloud.criteria.remove("B")
        w.cloud.break_map("garbage")

        assert (await w.run(rebuild_alias_map_from_cache=True)).ok

        (alias_map,) = w.cloud.valid_maps()
        assert set(alias_map.entries) == {"A"}
        assert set(await w.cache()) == {"A"}


@pytest.mark.asyncio
async def test_rebuild_with_empty_cache_makes_everything_inactive():
    async with _world() as w:
        await w.clear_cache()
        w.cloud.break_map("garbage")

        assert (await w.run(rebuild_alias_map_from_cache=True)).ok

        (alias_map,) = w.cloud.valid_maps()
        assert {e.status for e in alias_map.entries.values()} == {"uploaded"}
        assert set(alias_map.entries) == set(BASE)
        assert await _active_filter(w.cloud) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{}, {"swallow_errors": True}])
async def test_unreadable_map_without_flag_writes_nothing_and_marks_resync(
    kwargs,
):
    """자동 검사(swallow_errors)·시작 reconcile·재동기화 버튼은 복구하지 않는다."""
    async with _world() as w:
        w.cloud.break_map("v2")

        for _ in range(2):  # 되풀이해도 같다(대시보드 30초 간격 검사)
            result = await w.run(**kwargs)

            assert result.ok is False
            assert w.cloud.writes == []
            state, error = await w.state()
            assert state == "needs_resync"
            assert error.startswith("alias_map parse failed")
        assert await w.cache() == {
            "A": ("기준 A", "active"),
            "B": ("기준 B", "uploaded"),
        }


@pytest.mark.asyncio
async def test_concurrent_rebuilds_write_once():
    async with _world() as w:
        w.cloud.break_map("garbage")

        results = await asyncio.gather(
            w.run(rebuild_alias_map_from_cache=True),
            w.run(rebuild_alias_map_from_cache=True),
        )

        assert sorted((r.ok, r.skipped) for r in results) == [
            (False, True),
            (True, False),
        ]
        assert len([x for x in w.cloud.writes if x.startswith("upload")]) == 1
        assert len(w.cloud.valid_maps()) == 1
        assert await w.state() == ("ok", None)


# --- 라우트: POST /api/admin/criteria/rebuild-alias-map ---


def _client(user, result, monkeypatch):
    from app.db import get_db
    from app.dependencies import get_current_user
    from app.main import app
    from app.routers.admin import criteria as criteria_router

    db = MagicMock()
    db.commit = AsyncMock()

    async def _db():
        yield db

    reconcile = AsyncMock(return_value=result)
    monkeypatch.setattr(criteria_router, "CriteriaVectorService", MagicMock())
    monkeypatch.setattr(
        criteria_router,
        "CriteriaReconciliationService",
        MagicMock(return_value=SimpleNamespace(reconcile=reconcile)),
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db
    return TestClient(app), reconcile, db


@pytest.fixture
def _clear_overrides():
    from app.main import app

    yield
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "result, status_code, commits",
    [
        (ReconcileResult(ok=True, count=2), 200, 1),
        (ReconcileResult(skipped=True), 409, 0),
        (ReconcileResult(error="삭제 실패"), 503, 1),
    ],
)
def test_rebuild_route_maps_result_to_status(
    result, status_code, commits, monkeypatch, _clear_overrides
):
    admin = SimpleNamespace(id=1, username="admin", is_admin=True)
    client, reconcile, db = _client(admin, result, monkeypatch)

    response = client.post("/api/admin/criteria/rebuild-alias-map")

    assert response.status_code == status_code
    reconcile.assert_awaited_once_with(rebuild_alias_map_from_cache=True)
    assert db.commit.await_count == commits
    assert "삭제 실패" not in response.text


def test_rebuild_route_rejects_non_admin(monkeypatch, _clear_overrides):
    user = SimpleNamespace(id=2, username="teacher", is_admin=False)
    client, reconcile, _ = _client(user, ReconcileResult(ok=True), monkeypatch)

    response = client.post("/api/admin/criteria/rebuild-alias-map")

    assert response.status_code == 403
    reconcile.assert_not_awaited()
