"""POST .../activate + /deactivate routes"""
import pytest


def test_activate_demotes_other_active_entries():
    """
    Behavioral checklist:
    1. POST /admin/criteria/{stable_id}/activate returns 200 with {stable_id, status:"active"}.
    2. alias_map.replace() called with: target stable_id → active, ANY other previously-active → uploaded.
    3. DB rows for both stable_ids updated accordingly.

    Covered by service-level tests + Wave 7 e2e.
    """
    pytest.skip("Structural test; covered by service-level tests + e2e")


def test_deactivate_demotes_to_uploaded():
    """POST .../deactivate sets status="uploaded", activated_at=None"""
    pytest.skip("Structural test")


def test_activate_route_is_registered():
    from app.routers.admin.criteria import router
    paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/api/admin/criteria/{stable_id}/activate" in paths
    assert "/api/admin/criteria/{stable_id}/deactivate" in paths
