"""Unit tests for criteria_reconciliation_service helpers."""
from app.schemas.alias_map import AliasMapEntry
from app.services.criteria_reconciliation_service import (
    _normalize_active_entries,
    legacy_surrogate_stable_id,
)


def test_normalize_keeps_multiple_real_actives():
    entries = {
        "sid_a": AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:00:00Z"),
        "sid_b": AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:01:00Z"),
        "sid_c": AliasMapEntry(alias=None, status="uploaded", activated_at=None),
    }
    result = _normalize_active_entries(entries)
    assert result["sid_a"].status == "active"
    assert result["sid_a"].activated_at == "2026-05-17T00:00:00Z"
    assert result["sid_b"].status == "active"
    assert result["sid_c"].status == "uploaded"


def test_normalize_demotes_legacy_active_only():
    legacy_sid = legacy_surrogate_stable_id("doc-1")
    entries = {
        legacy_sid: AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:00:00Z"),
        "sid_a": AliasMapEntry(alias=None, status="active", activated_at="2026-05-17T00:01:00Z"),
    }
    result = _normalize_active_entries(entries)
    assert result[legacy_sid].status == "uploaded"
    assert result[legacy_sid].activated_at is None
    assert result["sid_a"].status == "active"
