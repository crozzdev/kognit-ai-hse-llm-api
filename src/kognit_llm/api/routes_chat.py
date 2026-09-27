"""POST /chat/message route: the only HTTP entry to the agent (R1.1-R1.22).

Validates the request, seeds a ``TurnState``, fetches conversation context,
invokes the compiled turn graph under a fresh per-turn telemetry, and maps the
final state to a single complete ``ChatResponse`` (no streaming). Error-matrix
statuses (503/504/200) are surfaced from the terminal outcome.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from kognit_llm.agent.guard import CURRENT_TELEMETRY
from kognit_llm.agent.state import ErrorCategory, TurnOutcome, TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.api.models import ChatRequest, ChatResponse, normalize_message
from kognit_llm.observability.fields import ENVIRONMENT_LOG_VALUE
from kognit_llm.observability.logger import RequestLogger

if TYPE_CHECKING:
    from kognit_llm.agent.nodes.deps import NodeDeps
    from kognit_llm.config.settings import Settings

__all__ = ["build_chat_router"]

# turn_outcome -> HTTP status for the response (Condition matrix).
_OUTCOME_STATUS: dict[TurnOutcome, int] = {
    TurnOutcome.ANSWERED_DATA_QUERY: 200,
    TurnOutcome.ANSWERED_GENERAL_CHAT: 200,
    TurnOutcome.CLARIFICATION_REQUESTED: 200,
    TurnOutcome.SCOPE_REJECTED: 200,
    TurnOutcome.INTENT_UNRESOLVED: 200,
    TurnOutcome.FIREWALL_REJECTED: 200,
    TurnOutcome.WAREHOUSE_ERROR: 503,
    TurnOutcome.WAREHOUSE_TIMEOUT: 200,
    TurnOutcome.PROVIDER_ERROR: 200,
    TurnOutcome.TURN_TIMEOUT: 504,
    TurnOutcome.MODEL_CALL_LIMIT_REACHED: 200,
    TurnOutcome.INTERNAL_ERROR: 200,
}

_REJECTED_OUTCOMES = frozenset(
    {TurnOutcome.SCOPE_REJECTED, TurnOutcome.INTERNAL_ERROR}
)


def build_chat_router(
    settings: "Settings", deps: "NodeDeps", graph: Any, logger: RequestLogger
) -> APIRouter:
    """Return a router exposing ``POST /chat/message`` bound to the compiled graph."""
    router = APIRouter()

    @router.post("/chat/message")
    def chat_message(payload: ChatRequest, request: Request) -> Response:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        correlation_id = getattr(request.state, "correlation_id", request_id)
        conversation_id = payload.conversation_id or str(uuid.uuid4())
        message = normalize_message(payload.message)
        if not message or len(message) > settings.message_max_chars:
            # The field validator normally rejects these; guard the direct path.
            return _validation_response(request_id, conversation_id)

        started = datetime.now(UTC)
        context = deps.store.get_context("DEMO", conversation_id)
        seed = TurnState(
            request_id=request_id,
            conversation_id=conversation_id,
            raw_message=message,
            turn_started_at=started,
            conversation_context=list(context),
        )

        telemetry = TurnTelemetry(cold_start=False)
        token = CURRENT_TELEMETRY.set(telemetry)
        try:
            final = TurnState.model_validate(graph.invoke(seed))
        finally:
            CURRENT_TELEMETRY.reset(token)

        response = _to_response(final, request_id, conversation_id, settings)
        _log_request(
            logger, settings, final, telemetry, correlation_id, message, started
        )
        return response

    return router


def _log_request(
    logger: RequestLogger,
    settings: "Settings",
    state: TurnState,
    telemetry: TurnTelemetry,
    correlation_id: str,
    message: str,
    started: datetime,
) -> None:
    """Emit exactly one request log entry after the outcome is determined (R14.1)."""
    outcome = state.turn_outcome or TurnOutcome.INTERNAL_ERROR
    duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    fields: dict[str, Any] = {
        "request_id": state.request_id,
        "correlation_id": correlation_id,
        "conversation_id": state.conversation_id,
        "user_id": state.user_id,
        "timestamp": started.isoformat(timespec="milliseconds"),
        "turn_outcome": outcome.value,
        "scope_decision": state.scope_decision or "IN_SCOPE",
        "intent": state.intent or "NOT_CLASSIFIED",
        "context_turn_count": len(state.conversation_context),
        "message_length": len(message),
        "model_call_count": state.model_call_count,
        "query_outcome": "SUCCESS" if state.result_set is not None else "NOT_EXECUTED",
        "total_duration_ms": duration_ms,
        "service": "kognit-ai-hse-llm-api",
        "service_version": settings.service_version,
        "environment": ENVIRONMENT_LOG_VALUE.get(
            settings.environment, settings.environment
        ),
        "cold_start": telemetry.cold_start,
    }
    if state.error_category is not None:
        fields["error_category"] = state.error_category.value
    if state.firewall_verdict is not None:
        fields["firewall_verdict"] = (
            "ADMITTED" if state.firewall_verdict.verdict == "ADMIT" else "REJECTED"
        )
        if state.firewall_verdict.reason is not None:
            fields["firewall_reason_code"] = state.firewall_verdict.reason.value
    if telemetry.model_call_count >= 1:
        fields["prompt_tokens"] = telemetry.prompt_tokens
        fields["completion_tokens"] = telemetry.completion_tokens
        fields["prompt_version"] = settings.prompt_version
    for node, elapsed in telemetry.stage_ms.items():
        fields[f"stage_{node}_ms"] = elapsed
    logger.emit(fields)


def _to_response(
    state: TurnState,
    request_id: str,
    conversation_id: str,
    settings: "Settings",
) -> Response:
    outcome = state.turn_outcome or TurnOutcome.INTERNAL_ERROR
    status = _OUTCOME_STATUS.get(outcome, 200)

    intent = _response_intent(state, outcome)
    scope_decision = state.scope_decision or "IN_SCOPE"
    response_text = state.answer_text or "The request could not be completed."

    if status != 200:
        # Uniform failure body for 503/504 (R13.32).
        return JSONResponse(
            status_code=status,
            content={
                "error_category": (
                    state.error_category.value
                    if state.error_category
                    else ErrorCategory.INTERNAL_ERROR.value
                ),
                "message": response_text,
                "request_id": request_id,
            },
        )

    body = ChatResponse(
        response=response_text,
        conversation_id=conversation_id,
        intent=intent,
        request_id=request_id,
        scope_decision=scope_decision,
        query_executed=_query_executed(state, settings),
    )
    return JSONResponse(
        status_code=200,
        content=body.model_dump(exclude_none=True),
    )


def _response_intent(
    state: TurnState, outcome: TurnOutcome
) -> Literal["DATA_QUERY", "GENERAL_CHAT", "CLARIFICATION_NEEDED", "REJECTED"]:
    """Map the turn to the response ``intent`` value (R1.10)."""
    if state.scope_decision in ("OUT_OF_SCOPE", "UNSAFE"):
        return "REJECTED"
    if outcome == TurnOutcome.CLARIFICATION_REQUESTED:
        return "CLARIFICATION_NEEDED"
    if outcome == TurnOutcome.ANSWERED_GENERAL_CHAT:
        return "GENERAL_CHAT"
    if outcome == TurnOutcome.ANSWERED_DATA_QUERY:
        return "DATA_QUERY"
    if state.intent in ("DATA_QUERY", "GENERAL_CHAT", "CLARIFICATION_NEEDED"):
        return state.intent
    return "REJECTED"


def _query_executed(state: TurnState, settings: "Settings") -> str | None:
    """Include the executed SQL only when configured and a query ran (R1.12-R1.13)."""
    if settings.expose_executed_sql and state.generated_sql is not None and (
        state.result_set is not None
    ):
        return state.generated_sql.statement
    return None


def _validation_response(request_id: str, conversation_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error_category": ErrorCategory.VALIDATION_ERROR.value,
            "message": "The field 'message' is missing or invalid.",
            "request_id": request_id,
        },
    )
