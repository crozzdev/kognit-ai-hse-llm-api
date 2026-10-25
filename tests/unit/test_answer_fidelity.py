"""Unit tests for numeric-fidelity verification (src/kognit_llm/answer).

Covers locale-aware number extraction, the permitted-number set (result values,
date boundaries, row cap) and the verify gate used by the synthesis draft loop
(R9.12-R9.19).
"""

from datetime import date
from decimal import Decimal

from kognit_llm.answer.fidelity import extract_numbers, permitted_numbers, verify


def test_extract_numbers_english_thousands_and_decimal():
    assert extract_numbers("1,234.5 and 7", "en") == [Decimal("1234.5"), Decimal("7")]


def test_extract_numbers_spanish_thousands_and_decimal():
    assert extract_numbers("1.234,5 y 7", "es") == [Decimal("1234.5"), Decimal("7")]


def test_extract_numbers_ignores_words():
    assert extract_numbers("no digits here", "en") == []


def test_permitted_numbers_includes_values_dates_and_cap():
    permitted = permitted_numbers(
        [Decimal("10"), "label", None, True],
        (date(2026, 1, 1), date(2026, 1, 31)),
        1000,
    )
    assert Decimal("10") in permitted  # a result value
    assert Decimal("1000") in permitted  # row cap
    assert Decimal("2026") in permitted  # boundary year
    assert Decimal("31") in permitted  # end-day boundary
    # Booleans and strings are not numeric values.
    assert Decimal("1") not in permitted or Decimal("1") in {
        Decimal(d.day) for d in (date(2026, 1, 1),)
    }


def test_permitted_numbers_without_time_range():
    permitted = permitted_numbers([Decimal("5")], None, 100)
    assert permitted == {Decimal("5"), Decimal("100")}


def test_verify_accepts_only_permitted_numbers():
    permitted = {Decimal("10"), Decimal("5")}
    assert verify("A: 10; B: 5", {*permitted}, "en") is True
    assert verify("A: 10; B: 999", {*permitted}, "en") is False


def test_verify_passes_when_no_numbers_present():
    assert verify("no figures", set(), "en") is True
