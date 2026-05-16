"""
alias-map.txt 문서 관리 서비스

책임:
- rubric-store 내 type=alias_map 문서를 fetch / parse
- entries 변경 후 upload-then-delete 안전 순서로 재게시 (Task 8에서 추가)

설계: docs/superpowers/specs/2026-05-15-criteria-cloud-metadata-design.md §4-§6
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from app.schemas.alias_map import AliasMap
from app.services.alias_map_codec import (
    ALIAS_MAP_PAYLOAD_KEY,
    decode_alias_map_payload,
    encode_alias_map_payload,
)

logger = logging.getLogger(__name__)


class AliasMapParseError(RuntimeError):
    """Raised when an existing alias_map document cannot be parsed safely."""

    def __init__(self, doc_name: str, original_error: Exception):
        self.doc_name = doc_name
        self.original_error = original_error
        super().__init__(
            f"alias_map parse failed for {doc_name}: {original_error}"
        )


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
        if slv is None:
            values = []
        elif isinstance(slv, dict):
            values = list(slv.get("values", []))
        else:
            values = list(getattr(slv, "values", []) or [])
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
        """(doc_name, AliasMap) 또는 None을 반환. 기존 문서 파싱 실패 시 예외."""
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
                return doc.name, AliasMap.model_validate(payload)
            except Exception as e:
                logger.error(f"alias_map 파싱 실패: {e}")
                raise AliasMapParseError(doc.name, e) from e
        return None

    async def replace(self, alias_map: AliasMap, old_doc_name: Optional[str]) -> str:
        """
        새 alias-map.txt 문서를 업로드한 뒤(만 성공 시) 이전 문서를 삭제한다.
        upload-then-delete 순서로 부분 손실을 방지.
        """
        store = self._find_store()
        if not store:
            raise RuntimeError(f"rubric-store '{self._store_display_name}' 미존재")

        payload_chunks = encode_alias_map_payload(alias_map.model_dump(mode="json"))

        # alias-map.txt는 내용물이 중요하지 않음(메타데이터에 데이터가 들어있음).
        # File Search는 파일을 요구하므로 placeholder 텍스트를 임시 파일로.
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as tmp:
            tmp.write("alias-map placeholder; data lives in custom_metadata")
            tmp_path = tmp.name

        try:
            op = self._client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store.name,
                file=tmp_path,
                config={
                    "display_name": "alias-map",
                    "custom_metadata": [
                        {"key": "type", "string_value": "alias_map"},
                        {"key": ALIAS_MAP_PAYLOAD_KEY, "string_list_value": {"values": payload_chunks}},
                    ],
                },
            )
            elapsed = 0
            while not getattr(op, "done", False) and elapsed < 60:
                await asyncio.sleep(2)
                elapsed += 2
                try:
                    op = self._client.operations.get(op)
                except Exception:
                    break
            if not getattr(op, "done", False):
                raise TimeoutError("alias-map upload timeout")

            new_doc_name = op.response.document_name
        finally:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

        if old_doc_name:
            self._client.file_search_stores.documents.delete(name=old_doc_name)

        return new_doc_name
