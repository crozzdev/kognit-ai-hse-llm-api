"""Analytics coverage matrix wiring (R8.6-R8.9, R8.20, R8.24-R8.25, R8.30-R8.31).

Classifies a question into an unsupported category when it asks for something the
warehouse cannot serve (lost workdays, lost-time cases, employee-level analytics,
frequency/injury-rate/TRIR, free-text narrative, prediction), so the synthesizer
renders the ``METRIC_UNAVAILABLE`` template with no figure (R8.14, R8.35). Also
provides the two-range / two-location comparison difference (R8.30-R8.31) and the
potential-severity labelling (R8.20).
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from kognit_llm.nlu.value_resolver import fold_value

__all__ = [
    "UnsupportedCategory",
    "classify_unsupported",
    "comparison_difference",
    "is_potential_severity",
]

UnsupportedCategory = Literal[
    "lost_workdays",
    "employee_level",
    "rate_or_trir",
    "narrative_text",
    "prediction",
]


@dataclass(frozen=True, slots=True)
class _Rule:
    category: UnsupportedCategory
    pattern: re.Pattern[str]


def _compile(*fragments: str) -> re.Pattern[str]:
    return re.compile("|".join(fragments))


# Ordered so the first match wins; patterns are folded (accent/case-insensitive).
_UNSUPPORTED_RULES: tuple[_Rule, ...] = (
    _Rule(
        "lost_workdays",
        _compile(
            r"\blost workday(s)?\b", r"\bdias perdidos\b", r"\bjornadas perdidas\b",
            r"\blost[- ]time (accident|case|injury)\b", r"\blta\b",
            r"\btiempo perdido\b",
        ),
    ),
    _Rule(
        "employee_level",
        _compile(
            r"\bper employee\b", r"\bby employee\b", r"\bemployee[- ]level\b",
            r"\bpor empleado\b", r"\bpor trabajador\b", r"\bcada empleado\b",
            r"\bnombre del empleado\b", r"\bemployee name\b",
        ),
    ),
    _Rule(
        "rate_or_trir",
        _compile(
            r"\bfrequency rate\b", r"\btasa de frecuencia\b", r"\btrir\b",
            r"\binjury rate\b", r"\btasa de lesion(es)?\b", r"\bindice de frecuencia\b",
            r"\bltifr\b", r"\brecordable rate\b",
        ),
    ),
    _Rule(
        "narrative_text",
        _compile(
            r"\bnarrative\b", r"\bnarrativa\b", r"\bfree[- ]text\b",
            r"\bdescription text\b", r"\btexto libre\b",
            r"\bdescripcion del incidente\b",
            r"\bcomentario(s)?\b", r"\breport body\b",
        ),
    ),
    _Rule(
        "prediction",
        _compile(
            r"\bpredict\b", r"\bprediction\b", r"\bforecast\b", r"\bproject(ion)?\b",
            r"\bpredic(cion|e|ir)\b", r"\bpronostic(o|ar)\b", r"\bproyeccion\b",
            r"\bfuture (cause|severity|risk)\b",
        ),
    ),
)


def classify_unsupported(message: str) -> UnsupportedCategory | None:
    """Return the unsupported category a message asks for, or None (R8.6-R8.9)."""
    folded = fold_value(message)
    for rule in _UNSUPPORTED_RULES:
        if rule.pattern.search(folded):
            return rule.category
    return None


def comparison_difference(
    first: Decimal | int, second: Decimal | int
) -> Decimal:
    """Return the arithmetic difference stated in a two-range/two-location answer.

    The comparison itself is served by one grouped statement returning one row per
    range or per location (R8.30-R8.31); the synthesizer states each figure and
    this difference.
    """
    return Decimal(str(first)) - Decimal(str(second))


def is_potential_severity(message: str) -> bool:
    """True when the question names a potential/hypothetical/worst-case outcome (R8.20).

    When true, the generator groups on ``dim_incident_type.potential_severity`` and
    the synthesizer labels the figure as potential rather than actual severity.
    """
    folded = fold_value(message)
    return bool(
        re.search(
            r"\bpotential severity\b|\bgravedad potencial\b|\bseveridad potencial\b"
            r"|\bworst[- ]case\b|\bpotential outcome\b",
            folded,
        )
    )
