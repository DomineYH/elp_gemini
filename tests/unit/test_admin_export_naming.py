# tests/unit/test_admin_export_naming.py
import pytest

from app.utils.admin_export_naming import (
    build_filename_prefix,
    build_lessonplan_basename,
    build_report_basename,
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


@pytest.mark.parametrize(
    "name,upload_id,report_id,expected",
    [
        ("plan.pdf", 25, 7, "u00001__report_25__plan"),
        ("plan.pdf", None, 7, "u00001__report_r7__plan"),
        ("a/b:c.hwp", 25, 7, "u00001__report_25__a_b_c"),
        ("", 25, 7, "u00001__report_25__untitled"),
        (None, None, 7, "u00001__report_r7__untitled"),
    ],
)
def test_build_report_basename(name, upload_id, report_id, expected):
    assert (
        build_report_basename(1, name, upload_id=upload_id, report_id=report_id)
        == expected
    )


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"upload_id": 25}, "u00001__lessonplan_25__plan.pdf"),
        ({"upload_id": 25, "report_id": 7}, "u00001__lessonplan_25__plan.pdf"),
        ({"report_id": 7}, "u00001__lessonplan_r7__plan.pdf"),
        ({"ordinal": 2}, "u00001__lessonplan_fs2__plan.pdf"),
    ],
)
def test_build_lessonplan_basename(kwargs, expected):
    assert build_lessonplan_basename(1, "plan.pdf", **kwargs) == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("a/b:c.pdf", "u00001__lessonplan_25__a_b_c.pdf"),
        ("", "u00001__lessonplan_25__untitled"),
    ],
)
def test_build_lessonplan_basename_slugifies(name, expected):
    assert build_lessonplan_basename(1, name, upload_id=25) == expected


def test_build_lessonplan_basename_requires_a_number():
    with pytest.raises(ValueError):
        build_lessonplan_basename(1, "plan.pdf")
