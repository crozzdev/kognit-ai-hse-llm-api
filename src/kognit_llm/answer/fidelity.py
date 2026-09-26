"""Numeric-fidelity verification of a draft answer (R9.12-R9.16).

``verify`` confirms that every numeric literal in a model draft traces to a value
present in the warehouse result set, a boundary component of the resolved date
range (year, month, day of start and end), or the configured row cap (R9.12).
``extract_numbers`` is locale-aware: ``1.234,5`` (es) and ``1,234.5`` (en) both
parse to ``1234.5`` (R9.18-R9.19); ordinals and words are not numeric literals.
"""

import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

__all__ = ["extract_numbers", "permitted_numbers", "verify"]

Language = Literal["es", "en"]

# A run of digits with optional grouping and decimal separators.
_NUMBER_RE = re.compile(r"\d[\d.,]*\d|\d")


def permitted_numbers(
    result_values: Sequence[object],
    time_range: tuple[date, date] | None,
    row_cap: int,
) -> set[Decimal]:
    """Return every number a faithful draft may state (R9.12).

    That is: each numeric value present in the result set, each boundary
    component (year, month, day) of the resolved range's start and end dates, and
    the configured row cap.
    """
    permitted: set[Decimal] = {Decimal(row_cap)}
    for value in result_values:
        number = _as_decimal(value)
        if number is not None:
            permitted.add(number)
    if time_range is not None:
        start, end = time_range
        for boundary in (start, end):
            permitted.update(
                {Decimal(boundary.year), Decimal(boundary.month), Decimal(boundary.day)}
            )
    return permitted


def extract_numbers(text: str, language: Language) -> list[Decimal]:
    """Extract the numeric literals from ``text`` under the locale (R9.18-R9.19)."""
    numbers: list[Decimal] = []
    for token in _NUMBER_RE.findall(text):
        parsed = _parse_localized(token, language)
        if parsed is not None:
            numbers.append(parsed)
    return numbers


def verify(draft: str, permitted: set[Decimal], language: Language) -> bool:
    """True when every numeric literal in ``draft`` is permitted (R9.12-R9.13)."""
    return all(number in permitted for number in extract_numbers(draft, language))


def _parse_localized(token: str, language: Language) -> Decimal | None:
    """Normalize a localized numeric token to a ``Decimal``."""
    cleaned = token.strip(".,")
    if not cleaned:
        return None
    if language == "es":
        # es: '.' groups thousands, ',' is the decimal separator.
        normalized = cleaned.replace(".", "").replace(",", ".")
    else:
        # en: ',' groups thousands, '.' is the decimal separator.
        normalized = cleaned.replace(",", "")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _as_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))
    return None
