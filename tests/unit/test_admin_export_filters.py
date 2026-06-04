# tests/unit/test_admin_export_filters.py
from datetime import date

import pytest
from fastapi import HTTPException

from app.schemas.admin_export import (
    INCLUDE_KINDS,
    ExportFilters,
    parse_filters,
)


def test_parse_filters_defaults():
    f = parse_filters()
    assert isinstance(f, ExportFilters)
    assert f.date_from is None
    assert f.date_to is None
    assert f.user_ids is None
    assert f.include == INCLUDE_KINDS


def test_parse_filters_full():
    f = parse_filters(
        date_from="2026-01-01",
        date_to="2026-03-31",
        user_ids="1,2,42",
        include="reports,meta",
    )
    assert f.date_from == date(2026, 1, 1)
    assert f.date_to == date(2026, 3, 31)
    assert f.user_ids == [1, 2, 42]
    assert f.include == frozenset({"reports", "meta"})


def test_parse_filters_invalid_date():
    with pytest.raises(HTTPException) as exc:
        parse_filters(date_from="2026-13-99")
    assert exc.value.status_code == 400
    assert "date_from" in exc.value.detail


def test_parse_filters_inverted_range():
    with pytest.raises(HTTPException) as exc:
        parse_filters(date_from="2026-05-01", date_to="2026-04-30")
    assert exc.value.status_code == 400
    assert "date_from must be <= date_to" in exc.value.detail


def test_parse_filters_invalid_user_ids():
    with pytest.raises(HTTPException) as exc:
        parse_filters(user_ids="1,abc,3")
    assert exc.value.status_code == 400
    assert "user_ids" in exc.value.detail


def test_parse_filters_unknown_include_token():
    with pytest.raises(HTTPException) as exc:
        parse_filters(include="reports,evil")
    assert exc.value.status_code == 400
    assert "include" in exc.value.detail


def test_parse_filters_empty_user_ids_becomes_none():
    f = parse_filters(user_ids="")
    assert f.user_ids is None


def test_export_filters_has_no_role_region_career():
    """role, region, career_min, career_max must not exist on ExportFilters."""
    f = ExportFilters()
    for field in ("role", "region", "career_min", "career_max"):
        assert not hasattr(f, field), f"ExportFilters should not have {field}"


def test_parse_filters_ignores_role_kwarg():
    """parse_filters must not accept role — calling with it should error."""
    with pytest.raises(TypeError):
        parse_filters(role="teacher")


def test_parse_filters_ignores_region_kwarg():
    with pytest.raises(TypeError):
        parse_filters(region="서울")


def test_parse_filters_ignores_career_kwarg():
    with pytest.raises(TypeError):
        parse_filters(career_min="3")
