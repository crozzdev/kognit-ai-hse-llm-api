"""Unit tests for intent understanding (src/kognit_llm/nlu/intent.py).

Covers ``build_analytics_intent`` across the label passthroughs, the DATA_QUERY
happy path, the grouping/filter bounds and confidence gates, measure defaulting
and carry-over, date resolution outcomes (including FUTURE_PERIOD), limit
clamping, retained-field carry-over, and ``normalize_filter_values``
(R3.13-R3.37, R8.15-R8.17).
"""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from kognit_llm.nlu.dates import DateExpression, TimeRange
from kognit_llm.nlu.intent import (
    AnalyticsIntent,
    IntentFilter,
    Ordering,
    RawFilterTerm,
    RawIntent,
    build_analytics_intent,
    normalize_filter_values,
)

TZ = ZoneInfo("America/Bogota")
REQUEST_INSTANT = datetime(2024, 5, 15, 14, 30, tzinfo=TZ)
THRESHOLD = Decimal("0.70")
ROW_CAP = 100
LOOKBACK = 30


def _build(raw: RawIntent, *, retained: AnalyticsIntent | None = None):
    return build_analytics_intent(
        raw,
        request_instant=REQUEST_INSTANT,
        tz=TZ,
        first_day_of_week="MONDAY",
        row_cap=ROW_CAP,
        confidence_threshold=THRESHOLD,
        default_lookback_days=LOOKBACK,
        retained=retained,
    )


def _retained() -> AnalyticsIntent:
    return AnalyticsIntent(
        measure="severity_index",
        time_range=TimeRange(start_date=date(2024, 1, 1), end_date=date(2024, 1, 31)),
        grouping_attributes=["dim_location.plant"],
        filters=[
            IntentFilter(
                attribute="dim_shift.shift_name",
                operator="equals",
                values=["Night"],
            )
        ],
        ordering=Ordering(field="severity_index", direction="DESC"),
        limit=50,
        confidence=Decimal("0.95"),
    )


def test_general_chat_passthrough():
    outcome = _build(RawIntent(intent="GENERAL_CHAT", confidence=Decimal("0.90")))
    assert outcome.label == "GENERAL_CHAT"
    assert outcome.analytics_intent is None


def test_clarification_needed_passthrough():
    outcome = _build(
        RawIntent(
            intent="CLARIFICATION_NEEDED",
            confidence=Decimal("0.90"),
            clarification_reason="Which site?",
        )
    )
    assert outcome.label == "CLARIFICATION_NEEDED"
    assert outcome.clarification_reason == "Which site?"


def test_data_query_happy_path():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="this_month"),
            grouping_terms=["dim_location.plant"],
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.label == "DATA_QUERY"
    assert outcome.analytics_intent is not None
    intent = outcome.analytics_intent
    assert intent.measure == "incident_count"
    assert intent.grouping_attributes == ["dim_location.plant"]
    assert intent.time_range == TimeRange(
        start_date=date(2024, 5, 1), end_date=date(2024, 5, 15)
    )
    assert intent.limit == ROW_CAP


def test_too_many_groupings_clarifies():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="this_month"),
            grouping_terms=["a", "b", "c", "d"],
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.label == "CLARIFICATION_NEEDED"
    assert outcome.clarification_reason is not None


def test_too_many_filters_clarifies():
    terms = [
        RawFilterTerm(attribute=f"attr{i}", operator="equals", values=["x"])
        for i in range(6)
    ]
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="this_month"),
            filter_terms=terms,
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.label == "CLARIFICATION_NEEDED"


def test_confidence_below_threshold_clarifies():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="this_month"),
            confidence=Decimal("0.50"),
            clarification_reason="Not sure",
        )
    )
    assert outcome.label == "CLARIFICATION_NEEDED"
    assert outcome.clarification_reason == "Not sure"


def test_confidence_below_threshold_default_reason():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="this_month"),
            confidence=Decimal("0.50"),
        )
    )
    assert outcome.label == "CLARIFICATION_NEEDED"
    assert outcome.clarification_reason == "The question was ambiguous."


def test_measure_defaults_to_incident_count_when_date_present():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure=None,
            date_expression=DateExpression(kind="today"),
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.label == "DATA_QUERY"
    assert outcome.analytics_intent is not None
    assert outcome.analytics_intent.measure == "incident_count"


def test_measure_carry_over_from_retained():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure=None,
            date_expression=None,
            grouping_terms=["dim_shift.shift_name"],
            confidence=Decimal("0.90"),
        ),
        retained=_retained(),
    )
    assert outcome.label == "DATA_QUERY"
    assert outcome.analytics_intent is not None
    assert outcome.analytics_intent.measure == "severity_index"


def test_measure_none_clarifies():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure=None,
            date_expression=None,
            grouping_terms=["dim_shift.shift_name"],
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.label == "CLARIFICATION_NEEDED"
    assert outcome.clarification_reason == "Please state which measure to report."


def test_future_period_outcome():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(
                kind="explicit_range",
                start=date(2024, 6, 1),
                end=date(2024, 6, 30),
            ),
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.label == "FUTURE_PERIOD"
    assert outcome.analytics_intent is None


def test_unsupported_date_clarifies():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="unsupported"),
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.label == "CLARIFICATION_NEEDED"
    assert outcome.clarification_reason == "Please restate the time period."


def test_limit_clamped_above_row_cap():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="today"),
            requested_limit=5000,
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.analytics_intent is not None
    assert outcome.analytics_intent.limit == ROW_CAP


def test_limit_clamped_below_one():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="today"),
            requested_limit=0,
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.analytics_intent is not None
    assert outcome.analytics_intent.limit == 1


def test_limit_defaults_to_row_cap_when_unset():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="today"),
            requested_limit=None,
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.analytics_intent is not None
    assert outcome.analytics_intent.limit == ROW_CAP


def test_no_date_no_retained_uses_default_range():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=None,
            confidence=Decimal("0.90"),
        )
    )
    assert outcome.analytics_intent is not None
    assert outcome.analytics_intent.time_range == TimeRange(
        start_date=date(2024, 4, 15), end_date=date(2024, 5, 15)
    )


def test_time_range_carry_over_from_retained():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=None,
            confidence=Decimal("0.90"),
        ),
        retained=_retained(),
    )
    assert outcome.analytics_intent is not None
    assert outcome.analytics_intent.time_range == TimeRange(
        start_date=date(2024, 1, 1), end_date=date(2024, 1, 31)
    )


def test_filter_and_grouping_carry_over_from_retained():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="today"),
            grouping_terms=[],
            filter_terms=[],
            confidence=Decimal("0.90"),
        ),
        retained=_retained(),
    )
    assert outcome.analytics_intent is not None
    intent = outcome.analytics_intent
    assert intent.grouping_attributes == ["dim_location.plant"]
    assert intent.filters == [
        IntentFilter(
            attribute="dim_shift.shift_name", operator="equals", values=["Night"]
        )
    ]
    assert intent.ordering == Ordering(field="severity_index", direction="DESC")


def test_raw_filters_take_precedence_over_retained():
    outcome = _build(
        RawIntent(
            intent="DATA_QUERY",
            measure="incident_count",
            date_expression=DateExpression(kind="today"),
            filter_terms=[
                RawFilterTerm(
                    attribute="dim_location.plant",
                    operator="equals",
                    values=["Bogota"],
                )
            ],
            confidence=Decimal("0.90"),
        ),
        retained=_retained(),
    )
    assert outcome.analytics_intent is not None
    assert outcome.analytics_intent.filters == [
        IntentFilter(
            attribute="dim_location.plant", operator="equals", values=["Bogota"]
        )
    ]


def test_normalize_filter_values_maps_night():
    intent = AnalyticsIntent(
        measure="incident_count",
        time_range=TimeRange(start_date=date(2024, 5, 1), end_date=date(2024, 5, 15)),
        filters=[
            IntentFilter(
                attribute="dim_shift.shift_name",
                operator="equals",
                values=["night"],
            )
        ],
        limit=10,
        confidence=Decimal("0.90"),
    )
    normalized = normalize_filter_values(intent)
    assert normalized.filters[0].values == ["Night"]


def test_normalize_filter_values_no_filters_passthrough():
    intent = AnalyticsIntent(
        measure="incident_count",
        time_range=TimeRange(start_date=date(2024, 5, 1), end_date=date(2024, 5, 15)),
        limit=10,
        confidence=Decimal("0.90"),
    )
    assert normalize_filter_values(intent) is intent


def test_normalize_filter_values_non_string_passthrough():
    intent = AnalyticsIntent(
        measure="incident_count",
        time_range=TimeRange(start_date=date(2024, 5, 1), end_date=date(2024, 5, 15)),
        filters=[
            IntentFilter(
                attribute="dim_incident.incident_date",
                operator="equals",
                values=[date(2024, 5, 1)],
            )
        ],
        limit=10,
        confidence=Decimal("0.90"),
    )
    normalized = normalize_filter_values(intent)
    assert normalized.filters[0].values == [date(2024, 5, 1)]
