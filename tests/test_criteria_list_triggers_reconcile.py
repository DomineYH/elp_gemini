"""Issue #80 — 평가기준 목록 endpoint가 freshness dependency를 호출하는지 검증."""
import inspect


def _uses_dependency(endpoint, dep):
    sig = inspect.signature(endpoint)
    for p in sig.parameters.values():
        if hasattr(p.default, "dependency") and p.default.dependency is dep:
            return True
    return False


def test_admin_list_json_declares_freshness_dependency():
    from app.routers.admin.criteria import list_criteria_json
    from app.services.criteria_freshness import ensure_criteria_cache_fresh

    assert _uses_dependency(list_criteria_json, ensure_criteria_cache_fresh)


def test_admin_list_html_declares_freshness_dependency():
    # criteria_views.py exposes an HTML view function as the route endpoint.
    # The function name is the GET handler defined around lines 75-90.
    from app.routers.admin import criteria_views
    from app.services.criteria_freshness import ensure_criteria_cache_fresh

    # Find the GET handler in the module by inspecting its decorated routes.
    handlers = [
        obj
        for name, obj in vars(criteria_views).items()
        if inspect.iscoroutinefunction(obj) and not name.startswith("_")
    ]
    assert handlers, "no async handler functions found in criteria_views"
    # We expect at least the GET handler to depend on ensure_criteria_cache_fresh.
    assert any(
        _uses_dependency(h, ensure_criteria_cache_fresh) for h in handlers
    ), (
        "no async handler in app.routers.admin.criteria_views depends on "
        "ensure_criteria_cache_fresh"
    )
