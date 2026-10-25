"""Unit tests for dimension-value resolution (src/kognit_llm/nlu).

Covers the fold-and-match resolver and the plant/area location resolution with
its resolved / not-recognized / ambiguous outcomes (R8.11, R8.26-R8.27, R16.36).
"""

from kognit_llm.nlu.value_resolver import (
    fold_value,
    resolve_location,
    resolve_value,
)

_PLANTS = ("Bogotá Plant", "Medellín Plant")
_AREAS = ("Warehouse", "Loading Dock")


def test_fold_value_strips_accents_and_case():
    assert fold_value("  BOGOTÁ  ") == "bogota"
    assert fold_value("Medellín") == "medellin"


def test_resolve_value_matches_case_and_accent_insensitively():
    result = resolve_value("bogota plant", _PLANTS)
    assert result.outcome == "resolved"
    assert result.value == "Bogotá Plant"  # exact stored form returned


def test_resolve_value_miss_is_not_recognized():
    result = resolve_value("unknown site", _PLANTS)
    assert result.outcome == "not_recognized"
    assert result.value is None


def test_resolve_location_plant_only():
    result = resolve_location("medellin plant", _PLANTS, _AREAS)
    assert result.outcome == "resolved"
    assert result.value == "Medellín Plant"


def test_resolve_location_area_only():
    result = resolve_location("warehouse", _PLANTS, _AREAS)
    assert result.outcome == "resolved"
    assert result.value == "Warehouse"


def test_resolve_location_ambiguous_when_both_match():
    plants = ("Central",)
    areas = ("Central",)
    result = resolve_location("central", plants, areas)
    assert result.outcome == "ambiguous"
    assert result.interpretations == (
        "dim_location.plant=Central",
        "dim_location.area_on_site=Central",
    )


def test_resolve_location_no_match_is_not_recognized():
    result = resolve_location("nowhere", _PLANTS, _AREAS)
    assert result.outcome == "not_recognized"
