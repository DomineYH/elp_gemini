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
    assert f.role is None
    assert f.region is None
    assert f.include == INCLUDE_KINDS


def test_parse_filters_full():
    f = parse_filters(
        date_from="2026-01-01",
        date_to="2026-03-31",
        user_ids="1,2,42",
        role="teacher",
        region="서울",
        include="reports,meta",
    )
    assert f.date_from == date(2026, 1, 1)
    assert f.date_to == date(2026, 3, 31)
    assert f.user_ids == [1, 2, 42]
    assert f.role == "teacher"
    assert f.region == "서울"
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


def test_parse_filters_invalid_role():
    with pytest.raises(HTTPException) as exc:
        parse_filters(role="ghost")
    assert exc.value.status_code == 400


def test_parse_filters_unknown_include_token():
    with pytest.raises(HTTPException) as exc:
        parse_filters(include="reports,evil")
    assert exc.value.status_code == 400
    assert "include" in exc.value.detail


def test_parse_filters_empty_user_ids_becomes_none():
    f = parse_filters(user_ids="")
    assert f.user_ids is None


def test_parse_filters_career_range():
    f = parse_filters(career_min="3", career_max="10")
    assert f.career_min == 3
    assert f.career_max == 10


def test_parse_filters_career_min_only():
    f = parse_filters(career_min="5")
    assert f.career_min == 5
    assert f.career_max is None


def test_parse_filters_invalid_career():
    with pytest.raises(HTTPException) as exc:
        parse_filters(career_min="abc")
    assert exc.value.status_code == 400
    assert "career_min" in exc.value.detail


def test_parse_filters_negative_career():
    with pytest.raises(HTTPException) as exc:
        parse_filters(career_min="-1")
    assert exc.value.status_code == 400
    assert "career_min" in exc.value.detail


def test_parse_filters_inverted_career_range():
    with pytest.raises(HTTPException) as exc:
        parse_filters(career_min="10", career_max="5")
    assert exc.value.status_code == 400
    assert "career_min must be <= career_max" in exc.value.detail
