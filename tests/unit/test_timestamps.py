from datetime import datetime, timedelta, timezone

from app.utils.timestamps import KST, kst_today_start_utc_naive, utc_iso


def test_naive_is_treated_as_utc():
    value = datetime(2026, 10, 21, 10, 36, 54)
    assert utc_iso(value) == "2026-10-21T10:36:54+00:00"


def test_none_passes_through():
    assert utc_iso(None) is None


def test_aware_is_converted_to_utc():
    kst = timezone(timedelta(hours=9))
    value = datetime(2026, 10, 21, 19, 36, 54, tzinfo=kst)
    assert utc_iso(value) == "2026-10-21T10:36:54+00:00"


def test_kst_today_start_across_utc_date_change():
    # KST 08:59/09:00은 UTC 날짜가 바뀌는 지점. 둘 다 KST 같은 날이다.
    expected = datetime(2026, 10, 21, 15, 0)
    for hour, minute in ((8, 59), (9, 0)):
        now = datetime(2026, 10, 22, hour, minute, tzinfo=KST)
        assert kst_today_start_utc_naive(now) == expected


def test_kst_today_start_right_after_and_before_midnight():
    just_after = datetime(2026, 10, 22, 0, 0, 30, tzinfo=KST)
    assert kst_today_start_utc_naive(just_after) == datetime(
        2026, 10, 21, 15, 0
    )
    just_before = datetime(2026, 10, 21, 23, 59, tzinfo=KST)
    assert kst_today_start_utc_naive(just_before) == datetime(
        2026, 10, 20, 15, 0
    )


def test_kst_today_start_accepts_utc_aware_now():
    now = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
    assert kst_today_start_utc_naive(now) == datetime(2026, 10, 21, 15, 0)
