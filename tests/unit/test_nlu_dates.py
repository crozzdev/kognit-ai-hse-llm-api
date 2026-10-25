"""Unit tests for pure date resolution (src/kognit_llm/nlu/dates.py).

Covers every ``DateKind`` branch of ``resolve`` for both Monday- and
Sunday-based weeks where it matters, the unsupported/invalid branches that raise
``UnsupportedDateExpression``, the request-date clamping rules, and
``default_range`` (R3.8-R3.38).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from kognit_llm.nlu.dates import (
    DateExpression,
    TimeRange,
    UnsupportedDateExpression,
    clamp_to_request_date,
    default_range,
    resolve,
)

TZ = ZoneInfo("America/Bogota")

# A fixed reference instant: Wednesday 2024-05-15 at 14:30 local time.
REQUEST_INSTANT = datetime(2024, 5, 15, 14, 30, tzinfo=TZ)


def _resolve(expr: DateExpression, *, monday: bool = True) -> TimeRange:
    return resolve(
        expr,
        request_instant=REQUEST_INSTANT,
        tz=TZ,
        first_day_of_week="MONDAY" if monday else "SUNDAY",
    )


def test_today():
    rng = _resolve(DateExpression(kind="today"))
    assert rng == TimeRange(start_date=date(2024, 5, 15), end_date=date(2024, 5, 15))


def test_yesterday():
    rng = _resolve(DateExpression(kind="yesterday"))
    assert rng == TimeRange(start_date=date(2024, 5, 14), end_date=date(2024, 5, 14))


def test_this_week_monday_start():
    # 2024-05-15 is a Wednesday; Monday of that week is 2024-05-13.
    rng = _resolve(DateExpression(kind="this_week"), monday=True)
    assert rng == TimeRange(start_date=date(2024, 5, 13), end_date=date(2024, 5, 19))


def test_this_week_sunday_start():
    # Sunday-based week containing Wednesday 2024-05-15 starts 2024-05-12.
    rng = _resolve(DateExpression(kind="this_week"), monday=False)
    assert rng == TimeRange(start_date=date(2024, 5, 12), end_date=date(2024, 5, 18))


def test_last_week_monday_start():
    rng = _resolve(DateExpression(kind="last_week"), monday=True)
    assert rng == TimeRange(start_date=date(2024, 5, 6), end_date=date(2024, 5, 12))


def test_last_week_sunday_start():
    rng = _resolve(DateExpression(kind="last_week"), monday=False)
    assert rng == TimeRange(start_date=date(2024, 5, 5), end_date=date(2024, 5, 11))


def test_this_month():
    rng = _resolve(DateExpression(kind="this_month"))
    assert rng == TimeRange(start_date=date(2024, 5, 1), end_date=date(2024, 5, 31))


def test_last_month():
    rng = _resolve(DateExpression(kind="last_month"))
    assert rng == TimeRange(start_date=date(2024, 4, 1), end_date=date(2024, 4, 30))


def test_last_month_crosses_year_boundary():
    jan_instant = datetime(2024, 1, 10, 9, 0, tzinfo=TZ)
    rng = resolve(
        DateExpression(kind="last_month"),
        request_instant=jan_instant,
        tz=TZ,
        first_day_of_week="MONDAY",
    )
    assert rng == TimeRange(start_date=date(2023, 12, 1), end_date=date(2023, 12, 31))


def test_this_quarter():
    # May is in Q2 (Apr-Jun).
    rng = _resolve(DateExpression(kind="this_quarter"))
    assert rng == TimeRange(start_date=date(2024, 4, 1), end_date=date(2024, 6, 30))


def test_last_quarter():
    # Q1 is Jan-Mar.
    rng = _resolve(DateExpression(kind="last_quarter"))
    assert rng == TimeRange(start_date=date(2024, 1, 1), end_date=date(2024, 3, 31))


def test_last_quarter_crosses_year_boundary():
    q1_instant = datetime(2024, 2, 1, 9, 0, tzinfo=TZ)
    rng = resolve(
        DateExpression(kind="last_quarter"),
        request_instant=q1_instant,
        tz=TZ,
        first_day_of_week="MONDAY",
    )
    assert rng == TimeRange(start_date=date(2023, 10, 1), end_date=date(2023, 12, 31))


def test_this_year():
    rng = _resolve(DateExpression(kind="this_year"))
    assert rng == TimeRange(start_date=date(2024, 1, 1), end_date=date(2024, 12, 31))


def test_last_year():
    rng = _resolve(DateExpression(kind="last_year"))
    assert rng == TimeRange(start_date=date(2023, 1, 1), end_date=date(2023, 12, 31))


def test_last_n_days():
    # request date minus N minus 1 calendar days .. request date.
    rng = _resolve(DateExpression(kind="last_n_days", n_days=7))
    assert rng == TimeRange(start_date=date(2024, 5, 7), end_date=date(2024, 5, 15))


def test_last_n_days_none_raises():
    with pytest.raises(UnsupportedDateExpression):
        _resolve(DateExpression(kind="last_n_days", n_days=None))


@pytest.mark.parametrize("n_days", [0, 366])
def test_last_n_days_out_of_range_raises(n_days):
    with pytest.raises(UnsupportedDateExpression):
        _resolve(DateExpression(kind="last_n_days", n_days=n_days))


def test_named_month_with_year():
    rng = _resolve(DateExpression(kind="named_month", month=2, year=2023))
    assert rng == TimeRange(start_date=date(2023, 2, 1), end_date=date(2023, 2, 28))


def test_named_month_without_year_earlier_this_year():
    # March (<= current month May) resolves to this year.
    rng = _resolve(DateExpression(kind="named_month", month=3))
    assert rng == TimeRange(start_date=date(2024, 3, 1), end_date=date(2024, 3, 31))


def test_named_month_without_year_future_month_rolls_back():
    # August (> current month May) resolves to last year.
    rng = _resolve(DateExpression(kind="named_month", month=8))
    assert rng == TimeRange(start_date=date(2023, 8, 1), end_date=date(2023, 8, 31))


def test_named_month_missing_month_raises():
    with pytest.raises(UnsupportedDateExpression):
        _resolve(DateExpression(kind="named_month", month=None))


@pytest.mark.parametrize("month", [0, 13])
def test_named_month_out_of_range_raises(month):
    with pytest.raises(UnsupportedDateExpression):
        _resolve(DateExpression(kind="named_month", month=month))


def test_explicit_range():
    rng = _resolve(
        DateExpression(
            kind="explicit_range",
            start=date(2024, 1, 5),
            end=date(2024, 2, 10),
        )
    )
    assert rng == TimeRange(start_date=date(2024, 1, 5), end_date=date(2024, 2, 10))


def test_explicit_range_missing_dates_raises():
    with pytest.raises(UnsupportedDateExpression):
        _resolve(DateExpression(kind="explicit_range", start=date(2024, 1, 5)))


def test_explicit_range_reversed_raises():
    with pytest.raises(UnsupportedDateExpression):
        _resolve(
            DateExpression(
                kind="explicit_range",
                start=date(2024, 3, 1),
                end=date(2024, 1, 1),
            )
        )


def test_unsupported_kind_raises():
    with pytest.raises(UnsupportedDateExpression):
        _resolve(DateExpression(kind="unsupported"))


def test_resolve_uses_reference_timezone():
    # A UTC instant just after midnight UTC is still the previous day in Bogota
    # (UTC-5), so "today" must reflect the local date.
    utc_instant = datetime(2024, 5, 15, 3, 0, tzinfo=ZoneInfo("UTC"))
    rng = resolve(
        DateExpression(kind="today"),
        request_instant=utc_instant,
        tz=TZ,
        first_day_of_week="MONDAY",
    )
    assert rng == TimeRange(start_date=date(2024, 5, 14), end_date=date(2024, 5, 14))


def test_clamp_to_request_date_future_raises():
    rng = TimeRange(start_date=date(2024, 6, 1), end_date=date(2024, 6, 30))
    with pytest.raises(UnsupportedDateExpression, match="future_period"):
        clamp_to_request_date(rng, request_date=date(2024, 5, 15))


def test_clamp_to_request_date_end_past_request_is_clamped():
    rng = TimeRange(start_date=date(2024, 5, 1), end_date=date(2024, 5, 31))
    clamped = clamp_to_request_date(rng, request_date=date(2024, 5, 15))
    assert clamped == TimeRange(
        start_date=date(2024, 5, 1), end_date=date(2024, 5, 15)
    )


def test_clamp_to_request_date_normal_unchanged():
    rng = TimeRange(start_date=date(2024, 5, 1), end_date=date(2024, 5, 10))
    clamped = clamp_to_request_date(rng, request_date=date(2024, 5, 15))
    assert clamped == rng


def test_default_range():
    rng = default_range(request_date=date(2024, 5, 15), lookback_days=30)
    assert rng == TimeRange(start_date=date(2024, 4, 15), end_date=date(2024, 5, 15))
