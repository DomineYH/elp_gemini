# tests/unit/test_admin_export_naming.py
import pytest
from app.utils.admin_export_naming import (
    build_filename_prefix,
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
