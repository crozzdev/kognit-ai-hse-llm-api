"""intent_classification node: intent + analytics intent (R3.1-R3.28).

Issues one model call for a ``RawIntent`` and converts it to a self-contained
``AnalyticsIntent`` via the pure ``nlu.intent.build_analytics_intent``. Writes
``intent``, ``analytics_intent`` and ``model_call_count``. A validation/provider
failure yields ``REJECTED`` intent so the graph routes to ``terminal_error`` with
``INTENT_UNRESOLVED`` (R3.7).
"""

from decimal import Decimal
from zoneinfo import ZoneInfo

from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.nlu.intent import RawIntent, build_analytics_intent
from kognit_llm.providers.base import (
    CompletionRequest,
    Message,
    ProviderError,
)

__all__ = ["make_intent_classification"]

_SYSTEM = (
    "You classify an HSE analytics message into a RawIntent JSON object. Emit "
    "ONLY these fields, using EXACTLY these value vocabularies:\n"
    '- "intent": one of "DATA_QUERY", "GENERAL_CHAT", "CLARIFICATION_NEEDED".\n'
    '- "measure": one of "incident_count", "severity_index", "action_count", '
    "or null. Map synonyms: incidents/accidents/events -> incident_count; "
    "severity -> severity_index; actions/corrective actions -> action_count.\n"
    '- "date_expression": null, or an object {"kind": ..., and only the fields '
    'that kind needs}. "kind" is one of "today", "yesterday", "this_week", '
    '"last_week", "this_month", "last_month", "this_quarter", "last_quarter", '
    '"this_year", "last_year", "last_n_days" (with "n_days": int), '
    '"named_month" (with "month": 1-12 and optional "year": int), '
    '"explicit_range" (with "start" and "end" as "YYYY-MM-DD"). '
    "For a single calendar year such as 2025, use "
    '{"kind":"named_month"} is WRONG; use '
    '{"kind":"explicit_range","start":"2025-01-01","end":"2025-12-31"}. '
    "Never compute relative dates yourself; classify the kind only.\n"
    '- "grouping_terms": array of strings (dimension names) or [].\n'
    '- "filter_terms": array of objects '
    '{"attribute": str, "operator": one of "equals","not_equals","in",'
    '"greater_than","less_than","between", "values": array of strings}, or [].\n'
    '- "ordering": null or {"field": str, "direction": "ASC" or "DESC"}.\n'
    '- "requested_limit": integer or null.\n'
    '- "confidence": number 0..1 with two decimals (e.g. 0.90).\n'
    '- "clarification_reason": string or null.\n'
    "Respond with the JSON object only: no explanation, no reasoning, no "
    "markdown, no code fences, no text before or after the object.\n"
    'Example for "how many incidents were recorded in 2025?": '
    '{"intent":"DATA_QUERY","measure":"incident_count",'
    '"date_expression":{"kind":"explicit_range","start":"2025-01-01",'
    '"end":"2025-12-31"},"grouping_terms":[],"filter_terms":[],'
    '"ordering":null,"requested_limit":null,"confidence":0.95,'
    '"clarification_reason":null}'
)


def make_intent_classification(deps: NodeDeps):
    """Return the intent_classification node bound to ``deps``."""

    def node(state: TurnState, telemetry: TurnTelemetry) -> dict[str, object]:
        request = CompletionRequest[RawIntent](
            call_type="intent",
            system_instruction=_SYSTEM,
            messages=(Message(role="user", content=state.raw_message),),
            output_model=RawIntent,
            temperature=deps.settings.model_temperature,
            max_output_tokens=deps.settings.model_max_output_tokens,
            timeout_ms=deps.settings.model_timeout_ms,
            request_id=state.request_id,
        )
        try:
            result = deps.provider.complete(request)
        except ProviderError:
            return {
                "intent": "REJECTED",
                "model_call_count": state.model_call_count + 1,
            }
        telemetry.record_provider_call(
            "intent", result.prompt_tokens, result.completion_tokens
        )

        outcome = build_analytics_intent(
            result.output,
            request_instant=state.turn_started_at,
            tz=ZoneInfo(deps.settings.reference_timezone),
            first_day_of_week=deps.settings.first_day_of_week,
            row_cap=deps.settings.row_cap,
            confidence_threshold=Decimal(str(deps.settings.intent_confidence_threshold)),
            default_lookback_days=deps.settings.default_lookback_days,
            retained=_latest_retained_intent(state),
        )
        return _to_update(outcome, state.model_call_count + 1)

    return node


def _to_update(outcome, model_calls: int) -> dict[str, object]:
    if outcome.label == "DATA_QUERY":
        return {
            "intent": "DATA_QUERY",
            "analytics_intent": outcome.analytics_intent,
            "model_call_count": model_calls,
        }
    if outcome.label == "GENERAL_CHAT":
        return {"intent": "GENERAL_CHAT", "model_call_count": model_calls}
    # CLARIFICATION_NEEDED and FUTURE_PERIOD both terminate without a query;
    # both surface as CLARIFICATION_NEEDED intent for the response contract.
    return {"intent": "CLARIFICATION_NEEDED", "model_call_count": model_calls}


def _latest_retained_intent(state: TurnState):
    """Return the most recent retained DATA_QUERY analytics intent, if any (R3.25)."""
    for record in reversed(state.conversation_context):
        analytics = getattr(record, "analytics_intent", None)
        if analytics is not None:
            return analytics
    return None
