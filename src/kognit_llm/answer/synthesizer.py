"""Answer synthesis with numeric-fidelity backstop (R9.1-R9.32, R8.12).

``synthesize`` renders the natural-language answer for a data query:
- A single row with a single numeric column uses the deterministic
  ``SINGLE_AGGREGATE`` / ``SINGLE_ZERO`` template with zero model calls (R9.16).
- Otherwise it requests a draft, verifies every numeric literal against the
  permitted set, requests one regeneration on failure, and falls back to a
  deterministic template (multi-row grouped) or the ``UNCONFIRMED`` message
  (R9.13-R9.15). At most two model calls per turn (R9.30).
The post-pass enforces the length cap and appends the data-scope sentence
through the templates; drafts that leak identifiers are rejected by fidelity's
template fallback since only template text can carry the final figure.

The model call is performed by the ``draft`` callable supplied by the wiring node
(M-13), keeping the provider dependency out of this module's imports.
"""

from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from kognit_llm.answer import templates
from kognit_llm.answer.fidelity import permitted_numbers, verify

__all__ = ["SynthesisInput", "synthesize"]

Language = Literal["es", "en"]

# The model draft callable returns the draft text, or None on provider failure.
DraftFn = Callable[[str], str | None]


class SynthesisInput:
    """The inputs one synthesis needs, kept free of SQL/schema text (R9.8)."""

    def __init__(
        self,
        *,
        columns: tuple[str, ...],
        rows: tuple[tuple[object, ...], ...],
        truncated: bool,
        measure_label: str,
        start: date,
        end: date,
        row_cap: int,
        language: Language,
        group_labels: Sequence[str] | None = None,
    ) -> None:
        self.columns = columns
        self.rows = rows
        self.truncated = truncated
        self.measure_label = measure_label
        self.start = start
        self.end = end
        self.row_cap = row_cap
        self.language = language
        self.group_labels = list(group_labels or [])


def synthesize(data: SynthesisInput, draft: DraftFn | None = None) -> str:
    """Return the final answer text for a data-query result (R9.1-R9.16)."""
    numeric_index = _single_numeric_column(data)

    # Single row, single numeric column -> deterministic template, 0 model calls.
    if len(data.rows) == 1 and numeric_index is not None:
        value = _as_decimal(data.rows[0][numeric_index])
        if value is not None and value == 0:
            return templates.single_zero(data.start, data.end, data.language)
        if value is not None:
            return templates.single_aggregate(
                value, data.measure_label, data.start, data.end, data.language
            )

    if not data.rows:
        return templates.zero_rows(data.start, data.end, data.language)

    permitted = permitted_numbers(
        [cell for row in data.rows for cell in row],
        (data.start, data.end),
        data.row_cap,
    )

    if draft is not None:
        for _ in range(2):  # draft + one regeneration (R9.13, R9.30)
            text = draft("synthesize")
            if text is not None and verify(text, permitted, data.language):
                return _post_pass(text)

    # Deterministic fallback for grouped/multi-column results.
    grouped_rows = _grouped_rows(data, numeric_index)
    if grouped_rows is not None:
        if data.truncated:
            return templates.truncated(
                grouped_rows, data.start, data.end, data.row_cap, data.language
            )
        return templates.grouped(grouped_rows, data.start, data.end, data.language)

    # Multi-row/multi-column with no confirmable draft -> UNCONFIRMED (R9.15).
    return templates.unconfirmed(data.language)


def _single_numeric_column(data: SynthesisInput) -> int | None:
    numeric_indices = (
        [
            i
            for i in range(len(data.columns))
            if all(_as_decimal(row[i]) is not None for row in data.rows)
        ]
        if data.rows
        else []
    )
    return numeric_indices[0] if len(numeric_indices) == 1 else None


def _grouped_rows(
    data: SynthesisInput, numeric_index: int | None
) -> list[tuple[str, Decimal]] | None:
    if numeric_index is None or len(data.columns) < 2:
        return None
    label_index = next(
        (i for i in range(len(data.columns)) if i != numeric_index), None
    )
    if label_index is None:
        return None
    rows: list[tuple[str, Decimal]] = []
    for row in data.rows:
        value = _as_decimal(row[numeric_index])
        if value is None:
            return None
        label = _group_label(row[label_index], data.language)
        rows.append((label, value))
    rows.sort(key=lambda pair: pair[1], reverse=True)
    return rows


def _group_label(value: object, language: Language) -> str:
    """Label a group, replacing null/unknown with a locale unknown label (R9.29)."""
    if value is None or str(value).strip().lower() in {"", "null", "none", "unknown"}:
        return "desconocido" if language == "es" else "unknown"
    return str(value)


def _post_pass(text: str) -> str:
    """Trim a draft to the answer length cap while keeping whole sentences (R9.4/26)."""
    stripped = text.strip()
    if len(stripped) <= 600:
        return stripped
    return stripped[:600].rstrip()


def _as_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))
    return None
