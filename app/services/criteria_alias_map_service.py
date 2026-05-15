"""
alias-map.txt 문서 관리 서비스

책임:
- rubric-store 내 type=alias_map 문서를 fetch / parse
- entries 변경 후 upload-then-delete 안전 순서로 재게시 (Task 8에서 추가)

설계: docs/superpowers/specs/2026-05-15-criteria-cloud-metadata-design.md §4-§6
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.schemas.alias_map import AliasMap, empty_alias_map
from app.services.alias_map_codec import (
    ALIAS_MAP_PAYLOAD_KEY,
    decode_alias_map_payload,
)

logger = logging.getLogger(__name__)


def _meta_value(entry, field):
    if isinstance(entry, dict):
        return entry.get(field)
    return getattr(entry, field, None)


def _read_metadata_kv(custom_metadata):
    """custom_metadata 리스트 → {key: (string_value, [string_list values])}"""
    out = {}
    for m in custom_metadata or []:
        key = _meta_value(m, "key")
        sv = _meta_value(m, "string_value")
        slv = _meta_value(m, "string_list_value")
        values = []
        if slv is not None:
            values = list(getattr(slv, "values", None) or (slv.get("values") if isinstance(slv, dict) else []))
        out[key] = (sv, values)
    return out


class CriteriaAliasMapService:
    def __init__(self, client, store_display_name: str):
        self._client = client
        self._store_display_name = store_display_name

    def _find_store(self):
        for s in self._client.file_search_stores.list():
            if s.display_name == self._store_display_name:
                return s
        return None

    async def fetch(self) -> Optional[Tuple[str, AliasMap]]:
        """(doc_name, AliasMap) 또는 None을 반환. 파싱 실패 시 비어있는 맵으로 fallback."""
        store = self._find_store()
        if not store:
            return None
        for doc in self._client.file_search_stores.documents.list(parent=store.name):
            kv = _read_metadata_kv(getattr(doc, "custom_metadata", None))
            type_value = (kv.get("type") or (None, []))[0]
            if type_value != "alias_map":
                continue
            chunks = (kv.get(ALIAS_MAP_PAYLOAD_KEY) or (None, []))[1]
            try:
                payload = decode_alias_map_payload(chunks)
                if not payload:
                    return doc.name, empty_alias_map(_now_iso())
                return doc.name, AliasMap.model_validate(payload)
            except Exception as e:
                logger.error(f"alias_map 파싱 실패 — 비어있는 맵으로 fallback: {e}")
                return doc.name, empty_alias_map(_now_iso())
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
