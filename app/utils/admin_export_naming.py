"""관리자 일괄 내보내기에서 사용하는 파일명/슬러그 정규화 헬퍼.

순수 함수만 둔다. DB 세션/외부 I/O 의존 없음.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_FORBIDDEN_FILENAME_CHARS = re.compile(r"[\\/:*?\"<>|]+")
_EMAIL_SAFE_CHARS = re.compile(r"[^a-z0-9_]+")
_COLLAPSE_UNDERSCORES = re.compile(r"_+")


@dataclass(frozen=True)
class NormalizedProfile:
    role_code: str
    region_slug: str
    tenure: str
    tenure_kind: str  # "years" | "grade"
    email_slug: str


def slugify_email(email: str | None) -> str:
    if not email:
        return "noemail"
    lowered = email.lower().replace("@", "_at_").replace(".", "_")
    slug = _EMAIL_SAFE_CHARS.sub("_", lowered)
    slug = _COLLAPSE_UNDERSCORES.sub("_", slug).strip("_")
    return slug or "noemail"


def slugify_original_name(name: str) -> str:
    if not name:
        return "untitled"
    cleaned = _FORBIDDEN_FILENAME_CHARS.sub("_", name).strip()
    return cleaned or "untitled"


def normalize_profile_fields(
    role: str | None,
    profile,
    email: str | None,
) -> NormalizedProfile:
    role_code, tenure_kind = _role_code_and_tenure_kind(role)
    region_slug = _region_for(role, profile)
    tenure = _tenure_for(role, profile)
    return NormalizedProfile(
        role_code=role_code,
        region_slug=region_slug,
        tenure=tenure,
        tenure_kind=tenure_kind,
        email_slug=slugify_email(email),
    )


def build_filename_prefix(
    user_id: int, profile: NormalizedProfile
) -> str:
    tenure_token = _format_tenure_token(profile)
    return (
        f"{profile.role_code}-{profile.region_slug}-{tenure_token}"
        f"__u{user_id:05d}__{profile.email_slug}"
    )


# ----- internal helpers -----


def _role_code_and_tenure_kind(role: str | None) -> tuple[str, str]:
    if role == "teacher":
        return "T", "years"
    if role == "preservice_teacher":
        return "P", "grade"
    return "U", "years"


def _region_for(role: str | None, profile) -> str:
    if profile is None:
        return "미상"
    if role == "teacher":
        value = getattr(profile, "teacher_region", None)
    elif role == "preservice_teacher":
        value = getattr(profile, "preservice_university_region", None)
    else:
        value = None
    if not value:
        return "미상"
    return slugify_original_name(value)


def _tenure_for(role: str | None, profile) -> str:
    if profile is None:
        return "NA"
    if role == "teacher":
        value = getattr(profile, "teacher_career_years", None)
    elif role == "preservice_teacher":
        value = getattr(profile, "preservice_grade", None)
    else:
        value = None
    if value is None:
        return "NA"
    return str(value)


def _format_tenure_token(profile: NormalizedProfile) -> str:
    if profile.tenure == "NA":
        return "NA"
    if profile.tenure_kind == "years":
        return f"{profile.tenure}y"
    return f"G{profile.tenure}"
