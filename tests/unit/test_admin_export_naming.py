# tests/unit/test_admin_export_naming.py
import pytest
from app.utils.admin_export_naming import (
    NormalizedProfile,
    build_filename_prefix,
    normalize_profile_fields,
    slugify_email,
    slugify_original_name,
)


class _ProfileStub:
    def __init__(self, **kwargs):
        self.role = kwargs.get("role")
        self.teacher_region = kwargs.get("teacher_region")
        self.teacher_career_years = kwargs.get("teacher_career_years")
        self.preservice_university_region = kwargs.get(
            "preservice_university_region"
        )
        self.preservice_grade = kwargs.get("preservice_grade")


def test_normalize_teacher_full_fields():
    profile = _ProfileStub(
        role="teacher",
        teacher_region="서울",
        teacher_career_years=12,
    )
    out = normalize_profile_fields(
        "teacher", profile, "kim@example.com"
    )
    assert out.role_code == "T"
    assert out.region_slug == "서울"
    assert out.tenure == "12"
    assert out.tenure_kind == "years"
    assert out.email_slug == "kim_at_example_com"


def test_normalize_preservice_full_fields():
    profile = _ProfileStub(
        role="preservice_teacher",
        preservice_university_region="부산",
        preservice_grade=3,
    )
    out = normalize_profile_fields(
        "preservice_teacher", profile, "lee@x.co.kr"
    )
    assert out.role_code == "P"
    assert out.region_slug == "부산"
    assert out.tenure == "3"
    assert out.tenure_kind == "grade"
    assert out.email_slug == "lee_at_x_co_kr"


def test_normalize_missing_profile_uses_defaults():
    out = normalize_profile_fields(
        "teacher", profile=None, email=None
    )
    assert out.role_code == "T"
    assert out.region_slug == "미상"
    assert out.tenure == "NA"
    assert out.tenure_kind == "years"
    assert out.email_slug == "noemail"


def test_normalize_unknown_role_falls_back_to_U():
    out = normalize_profile_fields("admin", None, "a@b.com")
    assert out.role_code == "U"
    assert out.tenure_kind == "years"


def test_build_filename_prefix_teacher():
    profile = NormalizedProfile(
        role_code="T",
        region_slug="서울",
        tenure="12",
        tenure_kind="years",
        email_slug="kim_at_example_com",
    )
    assert (
        build_filename_prefix(42, profile)
        == "T-서울-12y__u00042__kim_at_example_com"
    )


def test_build_filename_prefix_preservice():
    profile = NormalizedProfile(
        role_code="P",
        region_slug="부산",
        tenure="3",
        tenure_kind="grade",
        email_slug="lee_at_x_co_kr",
    )
    assert (
        build_filename_prefix(43, profile)
        == "P-부산-G3__u00043__lee_at_x_co_kr"
    )


def test_build_filename_prefix_missing_tenure():
    profile = NormalizedProfile(
        role_code="T",
        region_slug="미상",
        tenure="NA",
        tenure_kind="years",
        email_slug="noemail",
    )
    assert (
        build_filename_prefix(7, profile)
        == "T-미상-NA__u00007__noemail"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("kim@example.com", "kim_at_example_com"),
        ("LEE.K@X.CO.KR", "lee_k_at_x_co_kr"),
        ("plus+tag@host.io", "plus_tag_at_host_io"),
        (None, "noemail"),
        ("", "noemail"),
    ],
)
def test_slugify_email(raw, expected):
    assert slugify_email(raw) == expected


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
