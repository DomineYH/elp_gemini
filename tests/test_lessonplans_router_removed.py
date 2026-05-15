"""Legacy /api/lessonplans router registration tests."""

from app.main import app


def test_legacy_lessonplans_router_is_not_registered():
    routes = [
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/lessonplans")
    ]

    assert routes == []
