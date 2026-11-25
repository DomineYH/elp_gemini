from datetime import date, datetime, timedelta, timezone

from app.utils.timestamps import (
    KST,
    kst_date_start_utc_naive,
    kst_text,
    kst_today_start_utc_naive,
    utc_iso,
)


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


def test_kst_date_start_is_previous_utc_day_15h():
    assert kst_date_start_utc_naive(date(2026, 10, 22)) == datetime(
        2026, 10, 21, 15, 0
    )


def test_kst_text_naive_is_treated_as_utc():
    assert kst_text(datetime(2026, 11, 25, 1, 57, 23)) == "2026-11-25 10:57"


def test_kst_text_aware_is_converted():
    utc = datetime(2026, 5, 15, 3, 21, tzinfo=timezone.utc)
    assert kst_text(utc) == "2026-05-15 12:21"
    assert kst_text(utc.astimezone(KST)) == "2026-05-15 12:21"


def test_kst_text_accepts_iso_strings():
    assert kst_text("2026-05-15T03:21:00Z") == "2026-05-15 12:21"
    assert kst_text("2026-11-25T01:52:48.015906Z") == "2026-11-25 10:52"
    assert kst_text("2026-05-15T00:00Z") == "2026-05-15 09:00"
    assert kst_text("2026-05-15 03:21:00") == "2026-05-15 12:21"


def test_kst_text_empty_is_dash():
    assert kst_text(None) == "-"
    assert kst_text("") == "-"


def test_kst_text_crosses_date_line():
    assert kst_text(datetime(2026, 11, 25, 23, 30)) == "2026-11-26 08:30"


def test_kst_text_custom_format():
    value = datetime(2026, 11, 25, 1, 57, 23)
    assert kst_text(value, "%Y-%m-%d %H:%M:%S") == "2026-11-25 10:57:23"


def test_kst_text_unparseable_string_is_shown_as_is():
    # 목록 라우터는 렌더링 예외를 삼켜 빈 목록을 보여 준다. 예외를 내면 안 된다.
    assert kst_text("not-a-date") == "not-a-date"


def test_kst_filter_is_registered_on_shared_env():
    from app.templating import templates

    assert templates.env.filters["kst"] is kst_text
