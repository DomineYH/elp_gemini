"""Admin criteria alias route registration tests."""

from app.routers.admin.criteria import router


def _route_paths() -> set[str]:
    return {route.path for route in router.routes if hasattr(route, "path")}


def test_legacy_id_alias_route_is_not_registered():
    legacy_suffix = "/display" + "-alias"

    assert f"/api/admin/criteria/{{criteria_id}}{legacy_suffix}" not in _route_paths()


def test_stable_id_alias_route_remains_registered():
    assert "/api/admin/criteria/{stable_id}/alias" in _route_paths()
