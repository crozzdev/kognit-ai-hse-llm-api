"""Dimension-value resolution by fold-and-match (D9, R5.23, R8.11, R8.26-R8.27, R16.36).

The approved function allow-list (R6.32) contains no ``lower`` or ``unaccent``, so
a SQL-side fold is unavailable by construction. This module folds the user's term
(NFKD, casefold, mark-stripping) against the enumerated stored values of an
attribute and binds the **exact stored value** as a parameter. A miss yields the
not-recognized signal (R8.11, R8.26); a term matching both a ``plant`` value and
an ``area_on_site`` value yields the ambiguous signal (R8.27).
"""

import unicodedata
from dataclasses import dataclass
from typing import Literal

__all__ = ["ResolvedValue", "fold_value", "resolve_location", "resolve_value"]

Outcome = Literal["resolved", "not_recognized", "ambiguous"]


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    """The outcome of resolving a user term against stored dimension values."""

    outcome: Outcome
    value: str | None = None
    # For an ambiguous location term, the two interpretations that both matched.
    interpretations: tuple[str, ...] = ()


def fold_value(text: str) -> str:
    """NFKD-decompose, strip combining marks and casefold (R16.36)."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold().strip()


def resolve_value(term: str, stored_values: tuple[str, ...]) -> ResolvedValue:
    """Bind ``term`` to its exact stored value, or signal a miss (R8.11, R8.26).

    Matching is case- and diacritic-insensitive; the returned ``value`` is the
    exact stored form, which is what the generator binds as a parameter.
    """
    folded = fold_value(term)
    for stored in stored_values:
        if fold_value(stored) == folded:
            return ResolvedValue(outcome="resolved", value=stored)
    return ResolvedValue(outcome="not_recognized")


def resolve_location(
    term: str,
    plant_values: tuple[str, ...],
    area_values: tuple[str, ...],
) -> ResolvedValue:
    """Resolve a location term against plant and area values (R8.27).

    A term matching a value in exactly one of the two attributes resolves to it.
    A term matching values in both is ambiguous and the caller asks the user to
    choose plant vs area. A term matching neither is not recognized.
    """
    plant = resolve_value(term, plant_values)
    area = resolve_value(term, area_values)
    plant_hit = plant.outcome == "resolved"
    area_hit = area.outcome == "resolved"

    if plant_hit and area_hit:
        return ResolvedValue(
            outcome="ambiguous",
            interpretations=(
                f"dim_location.plant={plant.value}",
                f"dim_location.area_on_site={area.value}",
            ),
        )
    if plant_hit:
        return plant
    if area_hit:
        return area
    return ResolvedValue(outcome="not_recognized")
