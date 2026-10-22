"""DB의 naive UTC datetime을 오프셋 붙은 ISO 문자열로 직렬화한다 (#163)."""

from datetime import date, datetime, time, timedelta, timezone

# zoneinfo 없이 고정 오프셋 (lessonplan_analysis_service와 같은 방식)
KST = timezone(timedelta(hours=9))


def utc_iso(value: datetime | None) -> str | None:
    """naive는 UTC로 간주하고, aware는 UTC로 변환해 '+00:00'을 붙인다."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def kst_today_start_utc_naive(now: datetime | None = None) -> datetime:
    """KST 오늘 00:00을 DB 비교용 naive UTC로 돌려준다 (#205)."""
    now = (now or datetime.now(KST)).astimezone(KST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def kst_date_start_utc_naive(d: date) -> datetime:
    """KST 날짜 d의 00:00을 DB 비교용 naive UTC로 돌려준다 (#211)."""
    start = datetime.combine(d, time.min, tzinfo=KST)
    return start.astimezone(timezone.utc).replace(tzinfo=None)
