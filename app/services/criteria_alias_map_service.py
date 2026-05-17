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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from app.schemas.alias_map import AliasMap
from app.services.alias_map_codec import (
    ALIAS_MAP_PAYLOAD_KEY,
    decode_alias_map_payload,
    encode_alias_map_payload,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParsedAliasMapDoc:
    name: str
    alias_map: AliasMap
    updated_at: datetime


@dataclass(frozen=True)
class _UnparseableAliasMapDoc:
    name: str
    error: Exception
    updated_at: Optional[datetime]


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


def _parse_updated_at(value) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("alias_map updated_at is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _try_parse_updated_at(value) -> Optional[datetime]:
    try:
        return _parse_updated_at(value)
    except Exception:
        return None


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
        """(doc_name, AliasMap) 또는 None을 반환."""
        store = self._find_store()
        if not store:
            return None

        parsed_docs: list[_ParsedAliasMapDoc] = []
        unparseable_docs: list[_UnparseableAliasMapDoc] = []
        alias_doc_names: list[str] = []

        for doc in self._client.file_search_stores.documents.list(parent=store.name):
            kv = _read_metadata_kv(getattr(doc, "custom_metadata", None))
            type_value = (kv.get("type") or (None, []))[0]
            if type_value != "alias_map":
                continue
            alias_doc_names.append(doc.name)
            chunks = (kv.get(ALIAS_MAP_PAYLOAD_KEY) or (None, []))[1]
            payload = None
            try:
                payload = decode_alias_map_payload(chunks)
                alias_map = AliasMap.model_validate(payload)
                parsed_docs.append(_ParsedAliasMapDoc(
                    name=doc.name,
                    alias_map=alias_map,
                    updated_at=_parse_updated_at(alias_map.updated_at),
                ))
            except Exception as e:
                logger.warning(
                    "alias_map parse failed for %s: %s",
                    doc.name,
                    e,
                    exc_info=True,
                )
                updated_at = (
                    _try_parse_updated_at(payload.get("updated_at"))
                    if isinstance(payload, dict)
                    else None
                )
                unparseable_docs.append(_UnparseableAliasMapDoc(
                    name=doc.name,
                    error=e,
                    updated_at=updated_at,
                ))

        if not alias_doc_names:
            return None

        if len(alias_doc_names) > 1:
            logger.warning(
                "multiple alias_map documents found; using newest valid doc: %s",
                alias_doc_names,
            )

        if not parsed_docs:
            first_bad = unparseable_docs[0]
            raise AliasMapParseError(first_bad.name, first_bad.error)

        parsed_docs.sort(key=lambda parsed: parsed.updated_at, reverse=True)
        newest = parsed_docs[0]

        for bad_doc in unparseable_docs:
            if (
                bad_doc.updated_at is None
                or bad_doc.updated_at >= newest.updated_at
            ):
                raise AliasMapParseError(bad_doc.name, bad_doc.error)

        cleanup_names = [parsed.name for parsed in parsed_docs[1:]]
        cleanup_names.extend(
            bad_doc.name
            for bad_doc in unparseable_docs
            if (
                bad_doc.updated_at is not None
                and bad_doc.updated_at < newest.updated_at
            )
        )
        for doc_name in cleanup_names:
            try:
                self._client.file_search_stores.documents.delete(
                    name=doc_name,
                    config={"force": True},
                )
            except Exception:
                logger.warning(
                    "stale alias_map cleanup failed for %s",
                    doc_name,
                    exc_info=True,
                )

        return newest.name, newest.alias_map

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
            self._client.file_search_stores.documents.delete(
                name=old_doc_name,
                config={"force": True},
            )

        return new_doc_name
