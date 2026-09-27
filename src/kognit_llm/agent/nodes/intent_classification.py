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
    "You classify an HSE analytics message into a RawIntent JSON object with "
    "intent (DATA_QUERY | GENERAL_CHAT | CLARIFICATION_NEEDED), an optional "
    "measure, an optional classified date_expression, grouping_terms, "
    "filter_terms, ordering, requested_limit, a confidence 0..1, and an optional "
    "clarification_reason. Never compute dates or resolve values yourself."
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
