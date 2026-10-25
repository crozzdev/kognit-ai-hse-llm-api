"""Unit tests for the deterministic NLU vocabulary (src/kognit_llm/nlu).

Covers the Intelex severity map and the attribute-aware filter-value resolver:
term folding, correctly-cased pass-through, and the no-vocabulary / no-match
fall-throughs that keep behaviour from regressing (R8.15-R8.23).
"""

import pytest

from kognit_llm.nlu.vocabulary import map_intelex_severity, resolve_filter_value


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("S0", "minor"),
        ("S1", "minor"),
        ("S2", "serious"),
        ("S3a", "serious"),
        ("S3b", "serious"),
        ("S4", "fatal"),
        ("S5", "fatal"),
    ],
)
def test_map_intelex_severity_known_codes(code, expected):
    assert map_intelex_severity(code) == expected


def test_map_intelex_severity_unknown_code_is_unknown():
    assert map_intelex_severity("S9") == "unknown"


def test_resolve_filter_value_shift_term_to_stored():
    assert resolve_filter_value("dim_shift.shift_name", "noche") == "Night"
    assert resolve_filter_value("shift", "night") == "Night"
    assert resolve_filter_value("turno", "manana") == "Morning"


def test_resolve_filter_value_severity_and_category():
    assert resolve_filter_value("severity", "leve") == "minor"
    assert resolve_filter_value("gravedad", "mortal") == "fatal"
    assert resolve_filter_value("category", "incidentes") == "Incident"
    assert resolve_filter_value("tipo", "near miss") == "Near Miss"


def test_resolve_filter_value_already_stored_form_passes_through():
    # A correctly-cased stored value folds to itself (branch 2).
    assert resolve_filter_value("shift", "NIGHT") == "Night"


def test_resolve_filter_value_unknown_attribute_returns_input():
    assert resolve_filter_value("dim_location.plant", "Bogota") == "Bogota"


def test_resolve_filter_value_no_match_returns_input():
    assert resolve_filter_value("shift", "weekend") == "weekend"
