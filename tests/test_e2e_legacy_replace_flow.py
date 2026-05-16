"""End-to-end: legacy surrogate가 살아 있는 alias_map → replace → activate.

기존 운영 환경 시뮬레이션(pre-v2 cloud doc이 stable_id 메타데이터 없이 존재).
이 테스트는 Tasks 1-4가 모두 정합한지 한 번에 확인한다.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.admin.criteria import (
    activate_by_stable_id,
    replace_legacy_criteria,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_reconciliation_service import (
    legacy_surrogate_stable_id,
)


@pytest.mark.asyncio
async def test_legacy_replace_then_activate_round_trip():
    old_doc = "fileSearchStores/s/documents/pre-v2"
    legacy_sid = legacy_surrogate_stable_id(old_doc)
    new_doc = "fileSearchStores/s/documents/v2-new"

    # 1) 활성화 직접 시도 → 새 UI를 안내하는 400
    db_activate = AsyncMock()
    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias_cls.return_value.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    legacy_sid: AliasMapEntry(
                        alias="기준 v1",
                        status="uploaded",
                        activated_at=None,
                    ),
                },
            ),
        ))
        alias_cls.return_value.replace = AsyncMock()
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(
                stable_id=legacy_sid,
                document_id=old_doc,
                status="uploaded",
            )
        )
        with pytest.raises(HTTPException) as exc:
            await activate_by_stable_id(
                stable_id=legacy_sid,
                current_admin=object(),
                _sync_ready=None,
                db=db_activate,
            )
    assert exc.value.status_code == 400
    assert "교체" in exc.value.detail

    # 2) replace 엔드포인트 호출
    file = SimpleNamespace(
        filename="rubric_v1.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db_replace = AsyncMock()
    with patch(
        "app.routers.admin.criteria.FileValidator"
    ) as validator_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        vec = vector_cls.return_value
        vec.file_search_service.client = MagicMock()
        vec.upload_criteria = AsyncMock(return_value={"document_id": new_doc})
        vec.delete_criteria = AsyncMock(return_value=True)

        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    legacy_sid: AliasMapEntry(
                        alias="기준 v1",
                        status="uploaded",
                        activated_at=None,
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock()

        repo = repo_cls.return_value
        repo.get_criteria_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(
                stable_id=legacy_sid,
                document_id=old_doc,
                display_alias="기준 v1",
            )
        )
        repo.insert = AsyncMock()

        result = await replace_legacy_criteria(
            stable_id=legacy_sid,
            file=file,
            current_admin=SimpleNamespace(username="admin"),
            _sync_ready=None,
            db=db_replace,
        )

    new_sid = result["new_stable_id"]
    assert new_sid != legacy_sid
    assert not new_sid.startswith("legacy_")
    # alias_map: legacy entry는 사라지고 새 entry가 alias를 승계
    publish_call = alias.replace.await_args.args[0]
    assert legacy_sid not in publish_call.entries
    assert publish_call.entries[new_sid].alias == "기준 v1"

    # 3) 새 stable_id로 activate 호출 — 정상 동작
    db_activate2 = AsyncMock()
    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias_cls.return_value.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:01:00Z",
                entries={
                    new_sid: AliasMapEntry(
                        alias="기준 v1",
                        status="uploaded",
                        activated_at=None,
                    ),
                },
            ),
        ))
        alias_cls.return_value.replace = AsyncMock()
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(
                stable_id=new_sid,
                status="uploaded",
                activated_at=None,
            )
        )

        out = await activate_by_stable_id(
            stable_id=new_sid,
            current_admin=object(),
            _sync_ready=None,
            db=db_activate2,
        )

    assert out == {"stable_id": new_sid, "status": "active"}
