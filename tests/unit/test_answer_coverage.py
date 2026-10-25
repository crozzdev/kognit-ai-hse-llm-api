"""Unit tests for the analytics coverage matrix (src/kognit_llm/answer).

Covers the unsupported-category classifier (each category plus the supported
case), the comparison difference, and potential-severity detection
(R8.6-R8.9, R8.20, R8.30-R8.31).
"""

from decimal import Decimal

import pytest

from kognit_llm.answer.coverage import (
    classify_unsupported,
    comparison_difference,
    is_potential_severity,
)


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("How many lost workdays last month?", "lost_workdays"),
        ("cuantos dias perdidos hubo", "lost_workdays"),
        ("incidents per employee", "employee_level"),
        ("incidentes por trabajador", "employee_level"),
        ("what is the frequency rate", "rate_or_trir"),
        ("muestrame el TRIR", "rate_or_trir"),
        ("show the incident narrative", "narrative_text"),
        ("texto libre del reporte", "narrative_text"),
        ("predict next month incidents", "prediction"),
        ("pronostico de severidad", "prediction"),
    ],
)
def test_classify_unsupported_detects_each_category(message, category):
    assert classify_unsupported(message) == category


def test_classify_unsupported_supported_question_returns_none():
    assert classify_unsupported("How many incidents last month?") is None


def test_comparison_difference():
    assert comparison_difference(10, 3) == Decimal("7")
    assert comparison_difference(Decimal("2.5"), Decimal("1.0")) == Decimal("1.5")


@pytest.mark.parametrize(
    "message",
    [
        "what is the potential severity",
        "gravedad potencial de este evento",
        "worst-case outcome",
    ],
)
def test_is_potential_severity_true(message):
    assert is_potential_severity(message) is True


def test_is_potential_severity_false():
    assert is_potential_severity("actual severity breakdown") is False
