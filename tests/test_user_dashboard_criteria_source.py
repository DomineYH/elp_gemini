"""User dashboard criteria display source checks."""

import inspect
from types import SimpleNamespace

from app.routers import views
from app.routers.views import _criteria_documents_from_active


def test_dashboard_uses_alias_when_set():
    docs = _criteria_documents_from_active([
        SimpleNamespace(id=1, title="orig.pdf", display_alias="readable-name")
    ])

    assert docs == [{"id": 1, "name": "readable-name"}]


def test_dashboard_falls_back_to_title_when_alias_null():
    docs = _criteria_documents_from_active([
        SimpleNamespace(id=1, title="fallback-doc.pdf", display_alias=None)
    ])

    assert docs == [{"id": 1, "name": "fallback-doc.pdf"}]


def test_dashboard_does_not_call_cloud():
    src = inspect.getsource(views.user_dashboard)

    assert "CriteriaVectorService" not in src
    assert "list_criteria_documents" not in src
