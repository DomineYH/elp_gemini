# tests/unit/test_criteria_manifest_schema.py
import pytest
from pydantic import ValidationError

from app.schemas.criteria_manifest import (
    Manifest,
    ManifestEntry,
    MANIFEST_SCHEMA_VERSION,
)


def test_manifest_round_trips():
    raw = {
        "schema_version": 1,
        "generated_at": "2026-05-15T03:21:00Z",
        "criteria": [
            {
                "document_id": "files/abc",
                "title": "rubric.pdf",
                "display_alias": "1학기 평가기준",
                "status": "active",
                "created_at": "2026-05-12T08:15:00Z",
                "activated_at": "2026-05-12T08:20:00Z",
            }
        ],
    }
    m = Manifest.model_validate(raw)
    assert m.schema_version == MANIFEST_SCHEMA_VERSION
    assert len(m.criteria) == 1
    assert m.criteria[0].display_alias == "1학기 평가기준"


def test_manifest_rejects_invalid_status():
    raw = {
        "schema_version": 1,
        "generated_at": "2026-05-15T03:21:00Z",
        "criteria": [
            {
                "document_id": "files/abc",
                "title": "r.pdf",
                "status": "weird",
            }
        ],
    }
    with pytest.raises(ValidationError):
        Manifest.model_validate(raw)


def test_manifest_empty_list_allowed():
    m = Manifest.model_validate(
        {
            "schema_version": 1,
            "generated_at": "2026-05-15T03:21:00Z",
            "criteria": [],
        }
    )
    assert m.criteria == []


def test_manifest_unknown_schema_version_rejected():
    raw = {
        "schema_version": 999,
        "generated_at": "2026-05-15T03:21:00Z",
        "criteria": [],
    }
    with pytest.raises(ValidationError):
        Manifest.model_validate(raw)
