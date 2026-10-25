# tests/unit/test_admin_export_naming.py
import pytest

from app.utils.admin_export_naming import (
    build_filename_prefix,
    build_simsession_basename,
    slugify_original_name,
)


def test_build_filename_prefix():
    assert build_filename_prefix(user_id=42) == "u00042"


def test_build_filename_prefix_small_id():
    assert build_filename_prefix(user_id=1) == "u00001"


def test_build_filename_prefix_large_id():
    assert build_filename_prefix(user_id=99999) == "u99999"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1학년_수업지도안.pdf", "1학년_수업지도안.pdf"),
        ("path/with/slash.pdf", "path_with_slash.pdf"),
        ("back\\slash:colon*star?.md", "back_slash_colon_star_.md"),
        ("  leading_trail  ", "leading_trail"),
        ("", "untitled"),
        ("foo\x00bar", "foo_bar"),
        ("line\nbreak", "line_break"),
    ],
)
def test_slugify_original_name(raw, expected):
    assert slugify_original_name(raw) == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        (
            "우리나라 미래 인구 구성비.pdf",
            "u00003__simsession_10__우리나라 미래 인구 구성비__s7",
        ),
        ("a/b:c.hwp", "u00003__simsession_10__a_b_c__s7"),
        ("", "u00003__simsession_10__untitled__s7"),
    ],
)
def test_build_simsession_basename(name, expected):
    assert build_simsession_basename(3, 10, name, 7) == expected
