"""관리자 일괄 내보내기에서 사용하는 파일명/슬러그 정규화 헬퍼.

순수 함수만 둔다. DB 세션/외부 I/O 의존 없음.
"""

from __future__ import annotations

import os
import re

_FORBIDDEN_FILENAME_CHARS = re.compile(r"[\x00-\x1f\\/:*?\"<>|]+")


def slugify_original_name(name: str | None) -> str:
    if not name:
        return "untitled"
    cleaned = _FORBIDDEN_FILENAME_CHARS.sub("_", name).strip()
    return cleaned or "untitled"


def build_filename_prefix(user_id: int) -> str:
    return f"u{user_id:05d}"


def build_simsession_basename(
    user_id: int, upload_id: int, lessonplan_name: str | None, session_id: int
) -> str:
    """시뮬레이션 .md/.jsonl·다운로드 공통 이름 (확장자 없음).

    한 지도안으로 여러 번 시뮬레이션하므로 끝의 s{session_id}로 구분한다.
    """
    stem = os.path.splitext(lessonplan_name)[0] if lessonplan_name else ""
    return (
        f"{build_filename_prefix(user_id)}__simsession_{upload_id}__"
        f"{slugify_original_name(stem)}__s{session_id}"
    )
