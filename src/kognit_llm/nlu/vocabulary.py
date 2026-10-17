"""Spanish/English vocabulary mappings to allow-listed attributes and values.

Encodes the deterministic term mappings of R8.15-R8.18 and R8.23: category,
severity, shift and dimension terms map to exact allow-listed columns and stored
values, and raw Intelex severity codes map to the ETL severity values. The intent
classifier consults these so a Spanish question resolves to English stored values
(R8 coverage matrix).
"""

__all__ = [
    "CATEGORY_TERMS",
    "DIMENSION_TERMS",
    "INTELEX_SEVERITY",
    "SEVERITY_VALUE_TERMS",
    "SHIFT_VALUE_TERMS",
    "map_intelex_severity",
    "resolve_filter_value",
]

# Stored dim_incident_type.category values (defined once to avoid duplication).
_INCIDENT = "Incident"
_NEAR_MISS = "Near Miss"
_HAZARD = "Hazard"

# R8.15 — category terms to dim_incident_type.category values.
CATEGORY_TERMS: dict[str, str] = {
    "accidente": _INCIDENT,
    "accidentes": _INCIDENT,
    "incidente": _INCIDENT,
    "incidentes": _INCIDENT,
    "incident": _INCIDENT,
    "incidents": _INCIDENT,
    "casi accidente": _NEAR_MISS,
    "cuasi accidente": _NEAR_MISS,
    "casi accidentes": _NEAR_MISS,
    "near miss": _NEAR_MISS,
    "near misses": _NEAR_MISS,
    "peligro": _HAZARD,
    "peligros": _HAZARD,
    "condicion peligrosa": _HAZARD,
    "hazard": _HAZARD,
    "hazards": _HAZARD,
}

# R8.16 — severity value terms to dim_incident_type.severity values.
SEVERITY_VALUE_TERMS: dict[str, str] = {
    "leve": "minor",
    "minor": "minor",
    "grave": "serious",
    "serio": "serious",
    "serious": "serious",
    "fatal": "fatal",
    "mortal": "fatal",
}

# R8.17 — shift terms to dim_shift.shift_name values.
SHIFT_VALUE_TERMS: dict[str, str] = {
    "manana": "Morning",
    "dia": "Morning",
    "morning": "Morning",
    "day": "Morning",
    "noche": "Night",
    "night": "Night",
}

# R8.18 — Spanish dimension terms to allow-listed "table.column" attributes.
# Terms that map to a table (not a specific column) map to the table name.
DIMENSION_TERMS: dict[str, str] = {
    "planta": "dim_location.plant",
    "area": "dim_location.area_on_site",
    "gravedad": "dim_incident_type.severity",
    "severidad": "dim_incident_type.severity",
    "turno": "dim_shift.shift_name",
    "causa raiz": "dim_cause.root_cause",
    "estado": "dim_status.status",
    "lesion": "dim_injury.injury_type",
    "parte del cuerpo": "dim_injury.body_part",
    "epp": "dim_ppe",
    "equipo": "dim_equipment",
    "maquina": "dim_equipment",
    "acciones correctivas": "fact_actions",
}

# R8.18 — cause-subcategory value terms.
CAUSE_SUBCATEGORY_TERMS: dict[str, str] = {
    "acto inseguro": "Unsafe Act",
    "condicion insegura": "Unsafe Condition",
}

# R8.23 — raw Intelex severity codes to dim_incident_type.severity values.
INTELEX_SEVERITY: dict[str, str] = {
    "S0": "minor",
    "S1": "minor",
    "S2": "serious",
    "S3a": "serious",
    "S3b": "serious",
    "S4": "fatal",
    "S5": "fatal",
}


def map_intelex_severity(code: str) -> str:
    """Map an Intelex severity code to a value; unknown code -> 'unknown' (R8.23)."""
    return INTELEX_SEVERITY.get(code, "unknown")


# Attribute keyword -> term/value dictionary used to normalize a model-emitted
# filter value to its exact stored form (R8.15-R8.17). The model names the filter
# attribute inconsistently (``shift``, ``shift_name`` or ``dim_shift.shift_name``),
# so the keyword is matched as a substring of the (lower-cased) attribute. Only
# the enumerable dimensions with a curated vocabulary are covered; others pass
# through. Order matters: the first keyword found in the attribute wins.
_ATTRIBUTE_VALUE_TERMS: tuple[tuple[str, dict[str, str]], ...] = (
    ("shift", SHIFT_VALUE_TERMS),
    ("severity", SEVERITY_VALUE_TERMS),
    ("category", CATEGORY_TERMS),
)


def resolve_filter_value(attribute: str, value: str) -> str:
    """Return the exact stored value for a model-emitted filter ``value``.

    Matches case- and diacritic-insensitively against the curated vocabulary for
    ``attribute`` (for example a shift filter with ``"night"`` -> the stored
    ``"Night"``). The attribute is matched loosely because the model may name it
    ``shift``, ``shift_name`` or ``dim_shift.shift_name``. The match also accepts a
    value whose folded form already equals a stored value, so a correctly-cased
    value passes through. When the attribute has no curated vocabulary, or the
    value matches nothing, the original ``value`` is returned unchanged so
    behaviour never regresses.
    """
    from kognit_llm.nlu.value_resolver import fold_value

    attribute_lower = attribute.lower()
    terms = next(
        (d for keyword, d in _ATTRIBUTE_VALUE_TERMS if keyword in attribute_lower),
        None,
    )
    if terms is None:
        return value
    folded = fold_value(value)
    # 1) A user-term key (e.g. "night", "noche") folds to the stored value.
    for term, stored in terms.items():
        if fold_value(term) == folded:
            return stored
    # 2) The value already equals a stored value under folding (e.g. "NIGHT").
    for stored in set(terms.values()):
        if fold_value(stored) == folded:
            return stored
    return value
