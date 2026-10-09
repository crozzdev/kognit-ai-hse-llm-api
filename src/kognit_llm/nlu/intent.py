"""Intent classification and analytics-intent understanding (R3.1-R3.33).

The model emits a ``RawIntent`` (one classification, no computed dates or resolved
values — D9, D11). ``build_analytics_intent`` converts it to a self-contained
``AnalyticsIntent`` (R3.27): dates resolved by ``nlu.dates``, the confidence gate
and grouping/filter bounds applied, the limit clamped, and elliptical fields
carried over from the most recent retained ``DATA_QUERY`` intent (R3.25-R3.26).

The conversion is pure. The single model call that produces the ``RawIntent`` is
performed by the wiring node (M-13), which passes the parsed ``RawIntent`` here.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from kognit_llm.nlu.dates import (
    DateExpression,
    TimeRange,
    UnsupportedDateExpression,
    clamp_to_request_date,
    default_range,
    resolve,
)

__all__ = [
    "AnalyticsIntent",
    "IntentFilter",
    "IntentOutcome",
    "Ordering",
    "RawFilterTerm",
    "RawIntent",
    "build_analytics_intent",
]

Measure = Literal["incident_count", "severity_index", "action_count"]
FilterOp = Literal["equals", "not_equals", "in", "greater_than", "less_than", "between"]
IntentLabel = Literal["DATA_QUERY", "GENERAL_CHAT", "CLARIFICATION_NEEDED"]

_MAX_GROUPINGS = 3
_MAX_FILTERS = 5


class IntentFilter(BaseModel):
    """A resolved filter over an allow-listed attribute (R3.17)."""

    model_config = ConfigDict(extra="forbid")

    attribute: str
    operator: FilterOp
    values: Annotated[list[str | int | date], Field(min_length=1, max_length=20)]


class Ordering(BaseModel):
    """A result ordering over the measure or a grouping attribute (R3.18)."""

    model_config = ConfigDict(extra="forbid")

    field: str
    direction: Literal["ASC", "DESC"]


class AnalyticsIntent(BaseModel):
    """The seven-field, self-contained analytics intent (R3.5, R3.27)."""

    model_config = ConfigDict(extra="forbid")

    measure: Measure
    time_range: TimeRange
    grouping_attributes: Annotated[list[str], Field(max_length=3)] = []
    filters: Annotated[list[IntentFilter], Field(max_length=5)] = []
    ordering: Ordering | None = None
    limit: Annotated[int, Field(ge=1)]
    confidence: Annotated[Decimal, Field(ge=0, le=1, decimal_places=2)]


class RawFilterTerm(BaseModel):
    """A model-emitted, unresolved filter term (dimension term + operator + values)."""

    model_config = ConfigDict(extra="forbid")

    attribute: str
    operator: FilterOp
    values: Annotated[list[str], Field(min_length=1, max_length=20)]


class RawIntent(BaseModel):
    """Provider-facing intermediate; the model classifies only (D9, D11)."""

    model_config = ConfigDict(extra="forbid")

    intent: IntentLabel
    measure: Measure | None = None
    date_expression: DateExpression | None = None
    grouping_terms: list[str] = []
    filter_terms: list[RawFilterTerm] = []
    ordering: Ordering | None = None
    requested_limit: int | None = None
    confidence: Annotated[Decimal, Field(ge=0, le=1, decimal_places=2)]
    clarification_reason: str | None = None


class IntentOutcome(BaseModel):
    """The classifier result: a label plus, for DATA_QUERY, the analytics intent."""

    model_config = ConfigDict(extra="forbid")

    label: Literal[
        "DATA_QUERY", "GENERAL_CHAT", "CLARIFICATION_NEEDED", "FUTURE_PERIOD"
    ]
    analytics_intent: AnalyticsIntent | None = None
    clarification_reason: str | None = None


def build_analytics_intent(
    raw: RawIntent,
    *,
    request_instant: datetime,
    tz: ZoneInfo,
    first_day_of_week: Literal["MONDAY", "SUNDAY"],
    row_cap: int,
    confidence_threshold: Decimal,
    default_lookback_days: int,
    retained: AnalyticsIntent | None = None,
) -> IntentOutcome:
    """Convert a ``RawIntent`` into an ``IntentOutcome`` (R3.13-R3.33).

    Applies: measure defaulting to ``incident_count`` (R3.14); grouping/filter
    bounds -> CLARIFICATION when exceeded (R3.20); confidence gate (R3.22);
    date resolution and clamping (R3.34-R3.37); limit clamp to [1, row_cap]
    (R3.19); and carry-over of omitted fields from ``retained`` (R3.25-R3.26).
    """
    if raw.intent == "GENERAL_CHAT":
        return IntentOutcome(label="GENERAL_CHAT")
    if raw.intent == "CLARIFICATION_NEEDED":
        return IntentOutcome(
            label="CLARIFICATION_NEEDED",
            clarification_reason=raw.clarification_reason,
        )

    # DATA_QUERY path.
    if len(raw.grouping_terms) > _MAX_GROUPINGS or len(raw.filter_terms) > _MAX_FILTERS:
        return IntentOutcome(
            label="CLARIFICATION_NEEDED",
            clarification_reason=(
                f"At most {_MAX_GROUPINGS} breakdowns and {_MAX_FILTERS} filters "
                "are supported."
            ),
        )

    if raw.confidence < confidence_threshold:
        return IntentOutcome(
            label="CLARIFICATION_NEEDED",
            clarification_reason=raw.clarification_reason
            or "The question was ambiguous.",
        )

    measure = _resolve_measure(raw, retained)
    if measure is None:
        return IntentOutcome(
            label="CLARIFICATION_NEEDED",
            clarification_reason="Please state which measure to report.",
        )

    time_range_outcome = _resolve_time_range(
        raw,
        request_instant=request_instant,
        tz=tz,
        first_day_of_week=first_day_of_week,
        default_lookback_days=default_lookback_days,
        retained=retained,
    )
    if isinstance(time_range_outcome, IntentOutcome):
        return time_range_outcome
    time_range = time_range_outcome

    limit = _clamp_limit(raw.requested_limit, row_cap)
    grouping = list(raw.grouping_terms) or (
        retained.grouping_attributes if retained else []
    )
    filters = _carry_filters(raw, retained)

    return IntentOutcome(
        label="DATA_QUERY",
        analytics_intent=AnalyticsIntent(
            measure=measure,
            time_range=time_range,
            grouping_attributes=list(grouping),
            filters=filters,
            ordering=raw.ordering or (retained.ordering if retained else None),
            limit=limit,
            confidence=raw.confidence,
        ),
    )


def _resolve_measure(
    raw: RawIntent, retained: AnalyticsIntent | None
) -> Measure | None:
    if raw.measure is not None:
        return raw.measure
    # A count question without a named measure defaults to incident_count (R3.14),
    # but only when a period is present; otherwise carry-over decides.
    if raw.date_expression is not None:
        return "incident_count"
    if retained is not None:
        return retained.measure
    return None


def _resolve_time_range(
    raw: RawIntent,
    *,
    request_instant: datetime,
    tz: ZoneInfo,
    first_day_of_week: Literal["MONDAY", "SUNDAY"],
    default_lookback_days: int,
    retained: AnalyticsIntent | None,
) -> "TimeRange | IntentOutcome":
    request_date = request_instant.astimezone(tz).date()
    if raw.date_expression is None:
        if retained is not None:
            return retained.time_range
        return default_range(
            request_date=request_date, lookback_days=default_lookback_days
        )
    try:
        resolved = resolve(
            raw.date_expression,
            request_instant=request_instant,
            tz=tz,
            first_day_of_week=first_day_of_week,
        )
        return clamp_to_request_date(resolved, request_date=request_date)
    except UnsupportedDateExpression as err:
        if str(err) == "future_period":
            return IntentOutcome(label="FUTURE_PERIOD")
        return IntentOutcome(
            label="CLARIFICATION_NEEDED",
            clarification_reason="Please restate the time period.",
        )


def _clamp_limit(requested: int | None, row_cap: int) -> int:
    if requested is None:
        return row_cap
    return max(1, min(requested, row_cap))


def _carry_filters(
    raw: RawIntent, retained: AnalyticsIntent | None
) -> list[IntentFilter]:
    if raw.filter_terms:
        return [
            IntentFilter(
                attribute=term.attribute,
                operator=term.operator,
                values=list(term.values),
            )
            for term in raw.filter_terms
        ]
    return list(retained.filters) if retained else []
