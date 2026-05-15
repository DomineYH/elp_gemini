# app/schemas/criteria_manifest.py
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "rubric-manifest.json"

CriteriaStatus = Literal["uploaded", "active", "archived"]


class ManifestEntry(BaseModel):
    """매니페스트의 평가기준 한 항목."""

    document_id: str = Field(..., description="Gemini File Search 문서 ID")
    title: str = Field(..., description="원본 파일명/불변 명칭")
    display_alias: Optional[str] = Field(default=None, description="사용자 편집 이름")
    status: CriteriaStatus = Field(..., description="상태")
    created_at: Optional[datetime] = Field(default=None)
    activated_at: Optional[datetime] = Field(default=None)


class Manifest(BaseModel):
    """rubric-metadata-store 에 저장되는 단일 매니페스트 문서."""

    schema_version: int = Field(...)
    generated_at: datetime = Field(...)
    criteria: List[ManifestEntry] = Field(default_factory=list)

    @field_validator("schema_version")
    def _supported_version(cls, v: int) -> int:
        if v != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"manifest schema v{v} unsupported "
                f"(current={MANIFEST_SCHEMA_VERSION})"
            )
        return v
