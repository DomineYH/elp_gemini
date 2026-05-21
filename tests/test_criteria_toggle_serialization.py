"""
평가기준 활성/비활성 토글의 alias_map mutation 직렬화 회귀 테스트.

근거 (이슈 #78):
- 클라우드 alias-map 반영(upload-then-delete)이 진행 중인 동안 두 번째
  mutation 이 들어오면 alias_map 다중 문서 충돌 또는 needs_resync 마킹으로
  HTTP 503 이 발생한다.
- 해결: app.routers.admin.criteria 모듈에 _alias_map_mutation_lock 을 두고
  alias_map 변형 경로를 직렬화한다.

본 모듈은 동시 호출 시 alias_svc.replace 가 결코 동시에 두 번 진행 중이지
않음을 검증한다.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.routers.admin.criteria as criteria_module
from app.routers.admin.criteria import (
    activate_by_stable_id,
    deactivate_by_stable_id,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry


@pytest.fixture(autouse=True)
def _reset_alias_map_lock():
    """각 테스트 전에 _alias_map_mutation_lock 을 초기화.

    asyncio.Lock 은 최초 acquire 시 이벤트 루프에 바인딩된다.
    pytest-asyncio 가 테스트별로 새 루프를 만들면 기존 락이 이전 루프에
    묶여 RuntimeError 가 발생하므로 매 테스트마다 새 락으로 교체한다.
    """
    criteria_module._alias_map_mutation_lock = asyncio.Lock()
    yield


def _alias_map_with(stable_ids: list[str], status: str = "uploaded") -> AliasMap:
    return AliasMap(
        schema_version=1,
        updated_at="2026-05-21T00:00:00Z",
        entries={
            sid: AliasMapEntry(alias=None, status=status, activated_at=None)
            for sid in stable_ids
        },
    )


class _ConcurrencyProbe:
    """alias_svc.replace mock 으로 사용. 동시 진행 횟수를 추적한다."""

    def __init__(self, sleep_seconds: float = 0.05):
        self.in_progress = 0
        self.max_in_progress = 0
        self.calls = 0
        self._sleep = sleep_seconds

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        self.in_progress += 1
        if self.in_progress > self.max_in_progress:
            self.max_in_progress = self.in_progress
        await asyncio.sleep(self._sleep)
        self.in_progress -= 1
        return "fileSearchStores/s/documents/alias-map-new"


@pytest.mark.asyncio
async def test_concurrent_toggle_same_stable_id_is_serialized():
    """동일 stable_id 의 activate+deactivate 동시 호출이 직렬화된다."""
    stable_id = "01HTOGGLE"
    probe = _ConcurrencyProbe()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "fileSearchStores/s/documents/alias-map-old",
            _alias_map_with([stable_id]),
        ))
        alias.replace = probe

        repo = repo_cls.return_value
        row = MagicMock()
        row.status = "uploaded"
        row.activated_at = None
        repo.get_criteria_by_stable_id = AsyncMock(return_value=row)

        db = AsyncMock()

        results = await asyncio.gather(
            activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
            deactivate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
        )

    assert len(results) == 2
    assert probe.calls == 2, "두 mutation 모두 alias_svc.replace 를 호출해야 한다"
    assert probe.max_in_progress == 1, (
        "alias_svc.replace 가 동시에 두 번 진행 중이면 안 된다 "
        "(asyncio.Lock 직렬화 실패)"
    )


@pytest.mark.asyncio
async def test_concurrent_toggle_different_stable_ids_is_serialized():
    """서로 다른 stable_id 동시 호출도 alias_map 은 단일 문서이므로 직렬화된다."""
    sid_a = "01HTOGGLEA"
    sid_b = "01HTOGGLEB"
    probe = _ConcurrencyProbe()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "fileSearchStores/s/documents/alias-map-old",
            _alias_map_with([sid_a, sid_b]),
        ))
        alias.replace = probe

        repo = repo_cls.return_value
        row = MagicMock()
        row.status = "uploaded"
        row.activated_at = None
        repo.get_criteria_by_stable_id = AsyncMock(return_value=row)

        db = AsyncMock()

        results = await asyncio.gather(
            activate_by_stable_id(
                stable_id=sid_a,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
            activate_by_stable_id(
                stable_id=sid_b,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            ),
        )

    assert len(results) == 2
    assert probe.calls == 2
    assert probe.max_in_progress == 1


@pytest.mark.asyncio
async def test_toggle_lock_is_released_after_exception():
    """첫 mutation 이 예외로 실패해도 락은 풀려서 후속 호출이 진행된다."""
    stable_id = "01HTOGGLE"
    probe = _ConcurrencyProbe()

    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls, patch(
        "app.routers.admin.criteria.AppStateRepository"
    ) as state_cls, patch(
        "app.routers.admin.criteria._recover_status_mutation_from_cloud",
        new=AsyncMock(return_value=False),
    ):
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "fileSearchStores/s/documents/alias-map-old",
            _alias_map_with([stable_id]),
        ))
        # 첫 호출은 실패, 두 번째 호출은 정상 진행
        alias.replace = AsyncMock(side_effect=[
            RuntimeError("transient cloud error"),
            probe,
        ])

        repo = repo_cls.return_value
        row = MagicMock()
        row.status = "uploaded"
        row.activated_at = None
        repo.get_criteria_by_stable_id = AsyncMock(return_value=row)

        state = state_cls.return_value
        state.set = AsyncMock()

        db = AsyncMock()

        # 첫 호출: 500 예상
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await activate_by_stable_id(
                stable_id=stable_id,
                current_admin=object(),
                _sync_ready=None,
                db=db,
            )
        assert exc_info.value.status_code == 500

        # 두 번째 호출: 성공해야 함 (락이 풀렸어야 함)
        result = await deactivate_by_stable_id(
            stable_id=stable_id,
            current_admin=object(),
            _sync_ready=None,
            db=db,
        )
        assert result["status"] == "uploaded"
