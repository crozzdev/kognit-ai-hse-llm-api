"""Pure relative/absolute date resolution over the R3.29 table (R3.8-R3.38).

The model classifies a date expression into a ``DateExpression``; this module
resolves it to an absolute inclusive ``TimeRange`` deterministically, using
``zoneinfo`` for the configured reference timezone (D11). No model call and no
I/O happen here, so the relative-date round-trip property holds by construction.
"""

import calendar
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

__all__ = [
    "DateExpression",
    "TimeRange",
    "clamp_to_request_date",
    "default_range",
    "resolve",
]

DateKind = Literal[
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
    "last_n_days",
    "named_month",
    "explicit_range",
    "unsupported",
]


class TimeRange(BaseModel):
    """An inclusive absolute date range (R3.10)."""

    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date


class DateExpression(BaseModel):
    """A classified date expression; the model never computes dates (D11)."""

    model_config = ConfigDict(extra="forbid")

    kind: DateKind
    n_days: int | None = None
    month: int | None = None
    year: int | None = None
    start: date | None = None
    end: date | None = None


class UnsupportedDateExpression(Exception):
    """Raised when an expression falls outside the R3.29 table (-> clarification)."""


def resolve(
    expr: DateExpression,
    *,
    request_instant: datetime,
    tz: ZoneInfo,
    first_day_of_week: Literal["MONDAY", "SUNDAY"],
) -> TimeRange:
    """Resolve ``expr`` to an inclusive absolute range in ``tz`` (R3.8-R3.11, R3.29).

    Relative expressions are evaluated against the request instant's date in the
    reference timezone (R3.11). Raises ``UnsupportedDateExpression`` for the
    ``unsupported`` kind and for a reversed explicit range whose order is unknown
    (R3.32), so the caller classifies the turn as ``CLARIFICATION_NEEDED``.
    """
    today = request_instant.astimezone(tz).date()
    week_start_monday = first_day_of_week == "MONDAY"

    if expr.kind == "today":
        return TimeRange(start_date=today, end_date=today)
    if expr.kind == "yesterday":
        y = today - timedelta(days=1)
        return TimeRange(start_date=y, end_date=y)
    if expr.kind == "this_week":
        start = _week_start(today, week_start_monday)
        return TimeRange(start_date=start, end_date=start + timedelta(days=6))
    if expr.kind == "last_week":
        start = _week_start(today, week_start_monday) - timedelta(days=7)
        return TimeRange(start_date=start, end_date=start + timedelta(days=6))
    if expr.kind == "this_month":
        return _month_range(today.year, today.month)
    if expr.kind == "last_month":
        year, month = _shift_month(today.year, today.month, -1)
        return _month_range(year, month)
    if expr.kind == "this_quarter":
        return _quarter_range(today.year, _quarter_of(today.month))
    if expr.kind == "last_quarter":
        year, quarter = _shift_quarter(today.year, _quarter_of(today.month), -1)
        return _quarter_range(year, quarter)
    if expr.kind == "this_year":
        return TimeRange(
            start_date=date(today.year, 1, 1), end_date=date(today.year, 12, 31)
        )
    if expr.kind == "last_year":
        y = today.year - 1
        return TimeRange(start_date=date(y, 1, 1), end_date=date(y, 12, 31))
    if expr.kind == "last_n_days":
        return _last_n_days(expr, today)
    if expr.kind == "named_month":
        return _named_month(expr, today)
    if expr.kind == "explicit_range":
        return _explicit_range(expr)
    raise UnsupportedDateExpression(expr.kind)


def clamp_to_request_date(rng: TimeRange, *, request_date: date) -> TimeRange:
    """Clamp an end date that runs past the request date to it (R3.35).

    Raises ``UnsupportedDateExpression`` when the whole range is in the future
    (start after the request date), which the caller maps to the future-period
    answer (R3.34).
    """
    if rng.start_date > request_date:
        raise UnsupportedDateExpression("future_period")
    if rng.end_date > request_date:
        return TimeRange(start_date=rng.start_date, end_date=request_date)
    return rng


def default_range(*, request_date: date, lookback_days: int) -> TimeRange:
    """Default range when a DATA_QUERY states no date and none is retained (R3.37)."""
    return TimeRange(
        start_date=request_date - timedelta(days=lookback_days),
        end_date=request_date,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _week_start(day: date, monday: bool) -> date:
    # Monday=0 .. Sunday=6 in weekday(); Sunday-based weeks shift by one.
    if monday:
        return day - timedelta(days=day.weekday())
    return day - timedelta(days=(day.weekday() + 1) % 7)


def _month_range(year: int, month: int) -> TimeRange:
    last = calendar.monthrange(year, month)[1]
    return TimeRange(start_date=date(year, month, 1), end_date=date(year, month, last))


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def _quarter_of(month: int) -> int:
    return (month - 1) // 3 + 1


def _quarter_range(year: int, quarter: int) -> TimeRange:
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    last = calendar.monthrange(year, end_month)[1]
    return TimeRange(
        start_date=date(year, start_month, 1),
        end_date=date(year, end_month, last),
    )


def _shift_quarter(year: int, quarter: int, delta: int) -> tuple[int, int]:
    index = (year * 4 + (quarter - 1)) + delta
    return index // 4, index % 4 + 1


def _last_n_days(expr: DateExpression, today: date) -> TimeRange:
    if expr.n_days is None or not (1 <= expr.n_days <= 365):
        raise UnsupportedDateExpression("last_n_days out of range")
    # request date minus N minus 1 calendar days .. request date (R3.29).
    return TimeRange(
        start_date=today - timedelta(days=expr.n_days + 1),
        end_date=today,
    )


def _named_month(expr: DateExpression, today: date) -> TimeRange:
    if expr.month is None or not (1 <= expr.month <= 12):
        raise UnsupportedDateExpression("named_month missing month")
    if expr.year is not None:
        return _month_range(expr.year, expr.month)
    # Most recent occurrence whose last day is on or before the request date.
    year = today.year
    if expr.month > today.month:
        year -= 1
    return _month_range(year, expr.month)


def _explicit_range(expr: DateExpression) -> TimeRange:
    if expr.start is None or expr.end is None:
        raise UnsupportedDateExpression("explicit_range missing dates")
    if expr.start > expr.end:
        # Order cannot be determined; caller asks for clarification (R3.32).
        raise UnsupportedDateExpression("explicit_range reversed")
    return TimeRange(start_date=expr.start, end_date=expr.end)
