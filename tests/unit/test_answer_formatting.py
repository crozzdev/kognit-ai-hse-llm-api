"""Unit tests for locale-aware number/period rendering (src/kognit_llm/answer).

Covers thousands/decimal separators per locale, integer vs two-decimal rules,
negative values, and the full-month / full-year / arbitrary-range period forms
(R9.18-R9.23).
"""

from datetime import date
from decimal import Decimal

from kognit_llm.answer.formatting import format_number, format_period


def test_format_integer_english_groups_with_commas():
    assert format_number(1234567, "en") == "1,234,567"


def test_format_integer_spanish_groups_with_dots():
    assert format_number(1234567, "es") == "1.234.567"


def test_format_decimal_english_uses_dot():
    assert format_number(Decimal("1234.5"), "en") == "1,234.50"


def test_format_decimal_spanish_uses_comma():
    assert format_number(Decimal("1234.5"), "es") == "1.234,50"


def test_format_negative_decimal():
    assert format_number(Decimal("-12.5"), "en") == "-12.50"


def test_format_float_rounds_to_two_places():
    assert format_number(3.14159, "en") == "3.14"


def test_period_full_month_spanish():
    assert format_period(date(2026, 2, 1), date(2026, 2, 28), "es") == "febrero de 2026"


def test_period_full_month_english():
    assert format_period(date(2026, 2, 1), date(2026, 2, 28), "en") == "February 2026"


def test_period_full_year():
    assert format_period(date(2026, 1, 1), date(2026, 12, 31), "en") == "2026"


def test_period_arbitrary_range_is_isoformat():
    assert (
        format_period(date(2026, 1, 5), date(2026, 3, 10), "en")
        == "2026-01-05 .. 2026-03-10"
    )


def test_period_partial_month_is_not_full_month():
    # End before the last day -> arbitrary range, not the month form.
    assert (
        format_period(date(2026, 2, 1), date(2026, 2, 15), "es")
        == "2026-02-01 .. 2026-02-15"
    )
