"""Unit tests for the ``grouped`` answer template (src/kognit_llm/answer).

Cover both language branches and the ``not_enumerated`` suffix, plus the scope
sentence that every figure-bearing answer must carry (R8.12). These exercise the
single-return refactor of ``grouped`` across all of its branches.
"""

from datetime import date
from decimal import Decimal

from kognit_llm.answer import templates

_START = date(2026, 1, 1)
_END = date(2026, 1, 31)

_ROWS = [("Plant A", Decimal("10")), ("Plant B", Decimal("5"))]


def test_grouped_spanish_lists_rows_and_scope():
    text = templates.grouped(_ROWS, _START, _END, "es")

    assert "Plant A: 10" in text
    assert "Plant B: 5" in text
    assert "Durante" in text
    assert text.endswith(templates._SCOPE_SENTENCE["es"])


def test_grouped_english_lists_rows_and_scope():
    text = templates.grouped(_ROWS, _START, _END, "en")

    assert "Plant A: 10" in text
    assert "Plant B: 5" in text
    assert "During" in text
    assert text.endswith(templates._SCOPE_SENTENCE["en"])


def test_grouped_spanish_appends_not_enumerated_count():
    text = templates.grouped(_ROWS, _START, _END, "es", not_enumerated=3)

    assert "3 grupos adicionales no listados" in text
    assert text.endswith(templates._SCOPE_SENTENCE["es"])


def test_grouped_english_appends_not_enumerated_count():
    text = templates.grouped(_ROWS, _START, _END, "en", not_enumerated=3)

    assert "3 more groups not listed" in text
    assert text.endswith(templates._SCOPE_SENTENCE["en"])
