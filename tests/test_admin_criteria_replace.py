"""replace 라우터: legacy surrogate를 v2 stable_id 문서로 교체"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.admin.criteria import (
    replace_legacy_criteria,
    router,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry


def test_replace_route_is_registered():
    paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/api/admin/criteria/{stable_id}/replace" in paths


@pytest.mark.asyncio
async def test_replace_rejects_non_legacy_stable_id():
    file = SimpleNamespace(
        filename="r.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 r"),
    )
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await replace_legacy_criteria(
            stable_id="01HV2REAL",
            file=file,
            current_admin=SimpleNamespace(username="admin"),
            _sync_ready=None,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "legacy" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_replace_uploads_new_doc_preserves_alias_and_deletes_old():
    legacy_sid = "legacy_0123456789abcdef"
    old_doc = "fileSearchStores/s/documents/old"
    new_doc = "fileSearchStores/s/documents/new"

    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 r"),
    )
    db = AsyncMock()

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
                        alias="1학기 평가기준",
                        status="uploaded",
                        activated_at=None,
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock()

        repo = repo_cls.return_value
        repo.get_criteria_by_stable_id = AsyncMock(return_value=SimpleNamespace(
            stable_id=legacy_sid,
            document_id=old_doc,
            display_alias="1학기 평가기준",
        ))
        repo.insert = AsyncMock()

        result = await replace_legacy_criteria(
            stable_id=legacy_sid,
            file=file,
            current_admin=SimpleNamespace(username="admin"),
            _sync_ready=None,
            db=db,
        )

    assert result["old_stable_id"] == legacy_sid
    assert result["new_stable_id"].startswith("") and result["new_stable_id"] != legacy_sid
    assert result["document_id"] == new_doc

    # upload happened before any destructive op
    vec.upload_criteria.assert_awaited_once()
    upload_kwargs = vec.upload_criteria.await_args.kwargs
    assert upload_kwargs["title"] == "rubric.pdf"
    assert upload_kwargs["stable_id"] == result["new_stable_id"]

    # alias_map replace was called with new entry preserving alias
    alias.replace.assert_awaited_once()
    new_alias_map = alias.replace.await_args.args[0]
    assert legacy_sid not in new_alias_map.entries
    new_entry = new_alias_map.entries[result["new_stable_id"]]
    assert new_entry.alias == "1학기 평가기준"
    assert new_entry.status == "uploaded"
    assert new_entry.activated_at is None

    # old cloud document deleted after alias_map updated
    vec.delete_criteria.assert_awaited_once_with(document_id=old_doc)
