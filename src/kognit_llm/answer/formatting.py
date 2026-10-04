"""Locale-aware number and period rendering (R9.18-R9.23, R9.33).

Renders numeric values and resolved date ranges in Spanish or English:
- ``es`` uses ``.`` as the thousands separator and ``,`` as the decimal
  separator; ``en`` uses the reverse (R9.18-R9.19).
- Integers render without a fractional part; non-integers render with exactly two
  decimals (R9.20).
- A range spanning a full calendar month renders as the month name plus year
  (``febrero de 2026`` in es); a full calendar year renders as the year alone;
  any other range renders as ``YYYY-MM-DD`` .. ``YYYY-MM-DD`` (R9.21-R9.23).
Spanish diacritics are preserved without escaping (R9.33).
"""

import calendar
from datetime import date
from decimal import Decimal
from typing import Literal

__all__ = ["format_number", "format_period"]

Language = Literal["es", "en"]

_MONTHS = {
    "es": (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ),
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
}


def format_number(value: Decimal | int | float, language: Language) -> str:
    """Render ``value`` with locale separators and decimal rules (R9.18-R9.20)."""
    dec = Decimal(str(value))
    is_integer = dec == dec.to_integral_value()
    if is_integer:
        digits = f"{int(dec):,}"
        fraction = ""
    else:
        quantized = dec.quantize(Decimal("0.01"))
        integer_part = int(quantized.to_integral_value(rounding="ROUND_DOWN"))
        digits = f"{abs(integer_part):,}"
        frac_value = abs(quantized) - abs(integer_part)
        fraction = f"{frac_value:.2f}"[1:]  # ".NN"
        if quantized < 0:
            digits = "-" + digits

    if language == "es":
        digits = digits.replace(",", ".")
        fraction = fraction.replace(".", ",")
    return digits + fraction


def format_period(start: date, end: date, language: Language) -> str:
    """Render an inclusive date range per R9.21-R9.23."""
    if _is_full_month(start, end):
        month_name = _MONTHS[language][start.month - 1]
        if language == "es":
            return f"{month_name} de {start.year}"
        return f"{month_name} {start.year}"
    if _is_full_year(start, end):
        return str(start.year)
    return f"{start.isoformat()} .. {end.isoformat()}"


def _is_full_month(start: date, end: date) -> bool:
    if start.year != end.year or start.month != end.month:
        return False
    last_day = calendar.monthrange(start.year, start.month)[1]
    return start.day == 1 and end.day == last_day


def _is_full_year(start: date, end: date) -> bool:
    return (
        start.year == end.year
        and start.month == 1
        and start.day == 1
        and end.month == 12
        and end.day == 31
    )
