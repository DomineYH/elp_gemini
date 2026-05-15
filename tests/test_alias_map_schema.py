"""AliasMap / AliasMapEntry Pydantic 스키마 테스트"""
import pytest
from pydantic import ValidationError

from app.schemas.alias_map import AliasMap, AliasMapEntry


def test_entry_minimal_valid():
    e = AliasMapEntry(alias=None, status="uploaded", activated_at=None)
    assert e.alias is None
    assert e.status == "uploaded"


def test_entry_rejects_bad_status():
    with pytest.raises(ValidationError):
        AliasMapEntry(alias=None, status="garbage", activated_at=None)


def test_alias_map_serialize_and_parse_roundtrip():
    m = AliasMap(
        schema_version=1,
        updated_at="2026-05-15T00:00:00Z",
        entries={
            "01HXYZ": AliasMapEntry(alias="1학기 평가기준", status="active", activated_at="2026-05-15T00:00:00Z"),
            "01HABC": AliasMapEntry(alias=None, status="uploaded", activated_at=None),
        },
    )
    data = m.model_dump(mode="json")
    parsed = AliasMap.model_validate(data)
    assert parsed.entries["01HXYZ"].alias == "1학기 평가기준"
    assert parsed.entries["01HABC"].status == "uploaded"


def test_alias_map_rejects_unsupported_schema_version():
    with pytest.raises(ValidationError):
        AliasMap.model_validate({
            "schema_version": 999,
            "updated_at": "2026-05-15T00:00:00Z",
            "entries": {},
        })
