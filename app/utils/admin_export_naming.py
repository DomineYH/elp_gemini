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


def build_report_basename(
    user_id: int,
    lessonplan_name: str | None,
    *,
    upload_id: int | None,
    report_id: int,
) -> str:
    """보고서 이름 (확장자 없음). 지도안 번호가 없는 옛 보고서는 r{report_id}."""
    number = upload_id if upload_id is not None else f"r{report_id}"
    stem = os.path.splitext(lessonplan_name)[0] if lessonplan_name else ""
    return (
        f"{build_filename_prefix(user_id)}__report_{number}__"
        f"{slugify_original_name(stem)}"
    )


def build_lessonplan_basename(
    user_id: int,
    original_name: str | None,
    *,
    upload_id: int | None = None,
    report_id: int | None = None,
    ordinal: int | None = None,
) -> str:
    """원본 지도안 이름 (확장자 유지).

    번호 우선순위: 지도안 번호 → r{report_id} → 레거시 파일시스템 fs{ordinal}.
    """
    if upload_id is not None:
        number = str(upload_id)
    elif report_id is not None:
        number = f"r{report_id}"
    elif ordinal is not None:
        number = f"fs{ordinal}"
    else:
        raise ValueError("upload_id, report_id, ordinal 중 하나가 필요하다")
    return (
        f"{build_filename_prefix(user_id)}__lessonplan_{number}__"
        f"{slugify_original_name(original_name)}"
    )
