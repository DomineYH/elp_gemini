# app/schemas/admin_export.py
"""관리자 일괄 내보내기 쿼리 파라미터 스키마."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict
from pydantic.fields import FieldInfo


def _raw(val):
    """Unwrap FastAPI Query sentinels for direct (non-DI) calls."""
    return None if isinstance(val, FieldInfo) else val


INCLUDE_KINDS = frozenset(
    {"reports", "conversations", "lessonplans", "meta"}
)
class ExportFilters(BaseModel):
    model_config = ConfigDict(frozen=True)

    date_from: date | None = None
    date_to: date | None = None
    user_ids: list[int] | None = None
    include: frozenset[str] = INCLUDE_KINDS


def parse_filters(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    user_ids: str | None = Query(default=None),
    include: str | None = Query(default=None),
) -> ExportFilters:
    # Unwrap Query sentinels when called directly (not via Depends)
    date_from = _raw(date_from)
    date_to = _raw(date_to)
    user_ids = _raw(user_ids)
    include = _raw(include)

    parsed_from = _parse_date(date_from, "date_from")
    parsed_to = _parse_date(date_to, "date_to")
    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise HTTPException(
            status_code=400,
            detail="date_from must be <= date_to",
        )

    parsed_ids = _parse_user_ids(user_ids)
    parsed_include = _parse_include(include)

    return ExportFilters(
        date_from=parsed_from,
        date_to=parsed_to,
        user_ids=parsed_ids,
        include=parsed_include,
    )


def _parse_date(raw: str | None, field: str) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field}: expected YYYY-MM-DD, got {raw!r}",
        )


def _parse_user_ids(raw: str | None) -> list[int] | None:
    if raw is None or raw.strip() == "":
        return None
    out: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"user_ids: non-integer token {token!r}",
            )
    return out or None


def _parse_include(raw: str | None) -> frozenset[str]:
    if raw is None or raw.strip() == "":
        return INCLUDE_KINDS
    tokens = {t.strip() for t in raw.split(",") if t.strip()}
    unknown = tokens - INCLUDE_KINDS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"include: unknown token(s) {sorted(unknown)}; "
                f"allowed={sorted(INCLUDE_KINDS)}"
            ),
        )
    tokens.add("meta")  # meta는 항상 포함
    return frozenset(tokens)
