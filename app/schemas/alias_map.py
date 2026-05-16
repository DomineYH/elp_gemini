"""
alias-map.txt 의 페이로드(base64로 청크 인코딩되는 JSON) 스키마

설계: docs/superpowers/specs/2026-05-15-criteria-cloud-metadata-design.md §5.2
"""
from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


CURRENT_SCHEMA_VERSION = 1

CriteriaStatus = Literal["active", "uploaded", "archived"]


class AliasMapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: Optional[str] = Field(default=None, max_length=255)
    status: CriteriaStatus
    activated_at: Optional[str] = None  # ISO-8601, parsed downstream


class AliasMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = CURRENT_SCHEMA_VERSION
    updated_at: str
    entries: Dict[str, AliasMapEntry] = Field(default_factory=dict)


def empty_alias_map(now_iso: str) -> AliasMap:
    return AliasMap(schema_version=CURRENT_SCHEMA_VERSION, updated_at=now_iso, entries={})
