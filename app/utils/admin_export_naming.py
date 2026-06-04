"""관리자 일괄 내보내기에서 사용하는 파일명/슬러그 정규화 헬퍼.

순수 함수만 둔다. DB 세션/외부 I/O 의존 없음.
"""
from __future__ import annotations

import re


_FORBIDDEN_FILENAME_CHARS = re.compile(r"[\x00-\x1f\\/:*?\"<>|]+")


def slugify_original_name(name: str | None) -> str:
    if not name:
        return "untitled"
    cleaned = _FORBIDDEN_FILENAME_CHARS.sub("_", name).strip()
    return cleaned or "untitled"


def build_filename_prefix(user_id: int) -> str:
    return f"u{user_id:05d}"
