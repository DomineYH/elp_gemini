"""DELETE /admin/criteria/{stable_id}"""
import pytest


def test_delete_removes_cloud_alias_and_db():
    """
    Behavioral checklist:
    1. DELETE /admin/criteria/{stable_id} returns 200 with {stable_id, deleted:true}.
    2. CriteriaVectorService.delete_criteria(document_id) called once.
    3. CriteriaAliasMapService.replace() called with entries minus the deleted stable_id.
    4. DB row for stable_id is removed.
    """
    pytest.skip("Structural test; covered by service tests + e2e")


def test_delete_route_is_registered():
    from app.routers.admin.criteria import router
    routes_by_method = [(r.path, sorted(getattr(r, "methods", set()) or set())) for r in router.routes if hasattr(r, "path")]
    delete_routes = [(p, m) for p, m in routes_by_method if "DELETE" in m]
    # The new stable_id route should exist:
    assert any("/{stable_id}" in p for p, _ in delete_routes), f"DELETE /{{stable_id}} not registered. Routes: {delete_routes}"
