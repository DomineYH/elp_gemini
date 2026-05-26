"""Tests for Issue #80 — cloud alias_map.updated_at 기반 reconcile guard."""


def test_key_last_alias_map_updated_at_constant_exists():
    from app.repositories.app_state_repository import (
        KEY_LAST_ALIAS_MAP_UPDATED_AT,
    )
    assert KEY_LAST_ALIAS_MAP_UPDATED_AT == "criteria_last_alias_map_updated_at"
