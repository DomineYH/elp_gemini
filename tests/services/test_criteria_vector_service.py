"""CriteriaVectorService.active_stable_id_filter OR 결합 테스트."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_vector_service import CriteriaVectorService


def _patch_alias_map(alias_map: AliasMap):
    """CriteriaAliasMapService를 patch하여 주어진 alias_map을 반환하도록 설정."""
    return patch(
        "app.services.criteria_alias_map_service.CriteriaAliasMapService"
    )


@pytest.mark.asyncio
async def test_filter_zero_active_returns_none():
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-17T00:00:00Z",
        entries={
            "sid_a": AliasMapEntry(
                alias=None, status="uploaded", activated_at=None
            ),
        },
    )

    with _patch_alias_map(alias_map) as alias_cls:
        alias_cls.return_value.fetch = AsyncMock(
            return_value=("doc-name", alias_map)
        )
        result = await CriteriaVectorService.active_stable_id_filter(
            client=MagicMock(),
            store_display_name="rubric-store",
        )

    assert result is None


@pytest.mark.asyncio
async def test_filter_single_active_returns_equality():
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-17T00:00:00Z",
        entries={
            "sid_a": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-17T00:00:00Z",
            ),
        },
    )

    with _patch_alias_map(alias_map) as alias_cls:
        alias_cls.return_value.fetch = AsyncMock(
            return_value=("doc-name", alias_map)
        )
        result = await CriteriaVectorService.active_stable_id_filter(
            client=MagicMock(),
            store_display_name="rubric-store",
        )

    assert result == 'stable_id="sid_a"'


@pytest.mark.asyncio
async def test_filter_multiple_active_returns_or_expression():
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-17T00:00:00Z",
        entries={
            "sid_a": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-17T00:00:00Z",
            ),
            "sid_b": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-17T00:01:00Z",
            ),
        },
    )

    with _patch_alias_map(alias_map) as alias_cls:
        alias_cls.return_value.fetch = AsyncMock(
            return_value=("doc-name", alias_map)
        )
        result = await CriteriaVectorService.active_stable_id_filter(
            client=MagicMock(),
            store_display_name="rubric-store",
        )

    # 순서는 activated_at desc 기준
    assert result == '(stable_id="sid_b" OR stable_id="sid_a")'


@pytest.mark.asyncio
async def test_filter_escapes_quotes_in_stable_id():
    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-17T00:00:00Z",
        entries={
            'sid_"a': AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-17T00:00:00Z",
            ),
        },
    )

    with _patch_alias_map(alias_map) as alias_cls:
        alias_cls.return_value.fetch = AsyncMock(
            return_value=("doc-name", alias_map)
        )
        result = await CriteriaVectorService.active_stable_id_filter(
            client=MagicMock(),
            store_display_name="rubric-store",
        )

    assert result == 'stable_id="sid_\\"a"'
