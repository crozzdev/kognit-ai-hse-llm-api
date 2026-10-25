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


# ── Remaining template functions ──────────────────────────────────────────────


def _has_scope(text: str, language: str) -> bool:
    return text.endswith(templates._SCOPE_SENTENCE[language])


def test_single_aggregate_states_figure_and_scope():
    text = templates.single_aggregate(Decimal("42"), "incidentes", _START, _END, "es")
    assert "42" in text
    assert "incidentes" in text
    assert _has_scope(text, "es")


def test_single_zero_wording_per_language():
    es = templates.single_zero(_START, _END, "es")
    en = templates.single_zero(_START, _END, "en")
    assert "Ningun evento" in es
    assert "Zero events" in en
    assert _has_scope(es, "es")
    assert _has_scope(en, "en")


def test_zero_rows_states_period_and_scope():
    es = templates.zero_rows(_START, _END, "es")
    en = templates.zero_rows(_START, _END, "en")
    assert "No se encontraron registros" in es
    assert "No matching records" in en
    assert _has_scope(es, "es")
    assert _has_scope(en, "en")


def test_truncated_notes_first_rows():
    es = templates.truncated(_ROWS, _START, _END, 500, "es")
    en = templates.truncated(_ROWS, _START, _END, 500, "en")
    assert "primeras 500 filas" in es
    assert "first 500 rows" in en


def test_metric_unavailable_has_no_figure():
    es = templates.metric_unavailable("es")
    en = templates.metric_unavailable("en")
    assert "no esta disponible" in es
    assert "not available" in en


def test_value_not_recognized_lists_examples():
    es = templates.value_not_recognized("turno", ["Morning", "Night"], "es")
    en = templates.value_not_recognized("shift", ["Morning", "Night"], "en")
    assert "Morning, Night" in es
    assert "Morning, Night" in en


def test_value_not_recognized_caps_examples_at_ten():
    examples = [f"v{i}" for i in range(15)]
    text = templates.value_not_recognized("attr", examples, "en")
    assert "v9" in text
    assert "v10" not in text


def test_location_ambiguous():
    assert "planta" in templates.location_ambiguous("es")
    assert "plant" in templates.location_ambiguous("en")


def test_out_of_coverage():
    assert "Colombia" in templates.out_of_coverage("es")
    assert "Colombia" in templates.out_of_coverage("en")


def test_future_period():
    assert "futuro" in templates.future_period("es")
    assert "future" in templates.future_period("en")


def test_no_date_coverage():
    assert "cobertura" in templates.no_date_coverage("es")
    assert "coverage" in templates.no_date_coverage("en")


def test_clarification_includes_reason():
    assert "porque falta la fecha" in templates.clarification(
        "porque falta la fecha", "es"
    )
    assert "missing the date" in templates.clarification("missing the date", "en")


def test_capabilities_lists_categories():
    assert "incidentes" in templates.capabilities("es")
    assert "incident" in templates.capabilities("en")


def test_rejection_is_short_and_scope_bound():
    es = templates.rejection("es")
    en = templates.rejection("en")
    assert len(es) <= 300
    assert len(en) <= 300
    assert "seguridad" in es
    assert "Health and Safety" in en


def test_unconfirmed_has_no_numeric_literals():
    es = templates.unconfirmed("es")
    en = templates.unconfirmed("en")
    assert not any(ch.isdigit() for ch in es)
    assert not any(ch.isdigit() for ch in en)
