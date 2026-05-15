"""PATCH /admin/criteria/{stable_id}/alias"""
import pytest


def test_patch_alias_updates_alias_map_and_db():
    """
    Behavioral checklist (verified via service-level tests + Wave 7 e2e):
    1. PATCH /admin/criteria/{stable_id}/alias with body {alias: "..."} returns 200.
    2. CriteriaAliasMapService.replace() called with updated entries.alias.
    3. DB row for stable_id has display_alias updated.
    4. PDF is NOT re-uploaded (no upload_to_file_search_store call besides alias-map).
    """
    pytest.skip("Structural test; covered by Wave 2 service tests + Wave 7 e2e")


def test_patch_alias_route_is_registered():
    """Verify the new PATCH route is wired into the FastAPI router."""
    from app.routers.admin.criteria import router
    paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/api/admin/criteria/{stable_id}/alias" in paths
