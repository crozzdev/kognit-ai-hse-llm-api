"""Deterministic answer template catalogue (§Template catalogue, R2.11-R9.28).

Each template renders a bilingual (es/en) answer for one trigger. Templates that
report a figure append the mandatory data-scope sentence (R8.12); templates for
unavailability, ambiguity, out-of-coverage, future or clarification carry no
figure (R8.6-R8.9, R8.11, R8.13-R8.14, R8.35). Every answer excludes table names,
column names, SQL text and internal reason codes (R9.8), and stays within the
configured answer length (enforced by the synthesizer's post-pass, R9.4).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from kognit_llm.answer.formatting import format_number, format_period

__all__ = [
    "capabilities",
    "clarification",
    "grouped",
    "location_ambiguous",
    "metric_unavailable",
    "no_date_coverage",
    "future_period",
    "out_of_coverage",
    "rejection",
    "single_aggregate",
    "single_zero",
    "truncated",
    "unconfirmed",
    "value_not_recognized",
    "zero_rows",
]

Language = Literal["es", "en"]

_SCOPE_SENTENCE = {
    "es": (
        "La cobertura de datos corresponde a incidentes finalizados de Colombia y "
        '"The Americas".'
    ),
    "en": 'Data coverage is finalized Colombia and "The Americas" incidents.',
}


def _scope(language: Language) -> str:
    return _SCOPE_SENTENCE[language]


def single_aggregate(
    value: Decimal | int,
    measure_label: str,
    start: date,
    end: date,
    language: Language,
) -> str:
    """One figure with its measure label, period and the data-scope sentence."""
    number = format_number(value, language)
    period = format_period(start, end, language)
    if language == "es":
        return (
            f"Se registraron {number} {measure_label} durante {period}. "
            f"{_scope(language)}"
        )
    return (
        f"{number} {measure_label} were recorded during {period}. "
        f"{_scope(language)}"
    )


def single_zero(start: date, end: date, language: Language) -> str:
    """A single-row zero-value answer, worded distinctly from the zero-row case."""
    period = format_period(start, end, language)
    if language == "es":
        return (
            f"Ningun evento coincidio con los filtros aplicados durante {period}. "
            f"{_scope(language)}"
        )
    return (
        f"Zero events matched the applied filters during {period}. {_scope(language)}"
    )


def grouped(
    rows: Sequence[tuple[str, Decimal | int]],
    start: date,
    end: date,
    language: Language,
    not_enumerated: int = 0,
) -> str:
    """Top rows by measure, plus the count not enumerated and the scope sentence."""
    period = format_period(start, end, language)
    items = "; ".join(
        f"{label}: {format_number(value, language)}" for label, value in rows
    )
    if language == "es":
        text = f"Durante {period}: {items}."
        if not_enumerated > 0:
            text += f" ({not_enumerated} grupos adicionales no listados.)"
        return f"{text} {_scope(language)}"
    text = f"During {period}: {items}."
    if not_enumerated > 0:
        text += f" ({not_enumerated} more groups not listed.)"
    return f"{text} {_scope(language)}"


def zero_rows(start: date, end: date, language: Language) -> str:
    """No matching records, restating the period."""
    period = format_period(start, end, language)
    if language == "es":
        return (
            f"No se encontraron registros que coincidan con los filtros durante "
            f"{period}. {_scope(language)}"
        )
    return (
        f"No matching records were found for the applied filters during {period}. "
        f"{_scope(language)}"
    )


def truncated(
    rows: Sequence[tuple[str, Decimal | int]],
    start: date,
    end: date,
    row_cap: int,
    language: Language,
) -> str:
    """A grouped answer noting it reports the first ``row_cap`` rows."""
    base = grouped(rows, start, end, language)
    cap = format_number(row_cap, language)
    if language == "es":
        return f"{base} Se muestran las primeras {cap} filas de un resultado mayor."
    return f"{base} This reports the first {cap} rows of a larger result set."


def metric_unavailable(language: Language) -> str:
    """States the requested metric is unavailable, with no figure (R8.14, R8.35)."""
    if language == "es":
        return "La metrica solicitada no esta disponible en esta version del asistente."
    return "The requested metric is not available in this release of the assistant."


def value_not_recognized(
    attribute_label: str, examples: list[str], language: Language
) -> str:
    """Names the attribute and lists 1-10 stored values, no figure (R8.11, R8.26)."""
    listed = ", ".join(examples[:10])
    if language == "es":
        return (
            f"No reconoci el valor de {attribute_label}. Valores disponibles: {listed}."
        )
    return (
        f"I did not recognize that {attribute_label} value. Available values: {listed}."
    )


def location_ambiguous(language: Language) -> str:
    """Asks the user to choose plant vs area, no figure (R8.27)."""
    if language == "es":
        return (
            "Ese termino coincide con una planta y con un area. Cual desea consultar?"
        )
    return "That term matches both a plant and an area. Which did you mean?"


def out_of_coverage(language: Language) -> str:
    """States the loaded data scope, no figure (R8.13)."""
    if language == "es":
        return (
            "El almacen de datos contiene solo incidentes finalizados de Colombia y "
            '"The Americas".'
        )
    return (
        'The data warehouse contains finalized Colombia and "The Americas" '
        "incidents only."
    )


def future_period(language: Language) -> str:
    """States the requested period lies in the future (R3.34)."""
    if language == "es":
        return "El periodo solicitado esta en el futuro; no existen registros para el."
    return "The requested period is in the future; no records exist for it."


def no_date_coverage(language: Language) -> str:
    """States the period lies outside loaded coverage (R3.36)."""
    if language == "es":
        return "El periodo solicitado esta fuera de la cobertura de datos cargada."
    return "The requested period is outside the loaded data coverage."


def clarification(reason: str, language: Language) -> str:
    """Names the missing/ambiguous element, no table or column names (R3.4)."""
    if language == "es":
        return f"Podria aclarar su pregunta? {reason}"
    return f"Could you clarify your question? {reason}"


def capabilities(language: Language) -> str:
    """Lists supported categories, no warehouse query, no identifiers (R8.34, R9.11)."""
    if language == "es":
        return (
            "Puedo responder sobre conteos de incidentes, casi accidentes y "
            "peligros; severidad; lesiones; equipo de proteccion personal; acciones "
            "correctivas; y desgloses por fecha, ubicacion, turno, causa, estado, "
            "equipo y area de alto riesgo."
        )
    return (
        "I can answer about incident, near-miss and hazard counts; severity; "
        "injuries; personal protective equipment; corrective actions; and "
        "breakdowns by date, location, shift, cause, status, equipment and "
        "high-risk area."
    )


def rejection(language: Language) -> str:
    """The scope-rejection message: <=300 chars, no category or reasoning (R2.11)."""
    if language == "es":
        return (
            "Solo puedo responder preguntas analiticas aprobadas de seguridad y "
            "salud en el trabajo."
        )
    return "I can only answer approved Health and Safety analytics questions."


def unconfirmed(language: Language) -> str:
    """Fidelity failed twice on multi-row data: no numeric literals (R9.15)."""
    if language == "es":
        return "No pude confirmar las cifras solicitadas para esta pregunta."
    return "I could not confirm the figures for this question."
