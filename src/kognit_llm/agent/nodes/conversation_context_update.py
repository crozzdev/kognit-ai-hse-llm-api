"""conversation_context_update node: the sole graph exit (R10.23, R12.2).

Appends one ``TurnRecord`` for this turn to the store on every terminal path
(R10.23), excluding generated/executed SQL, schema context and result rows
(R12.23). Writes ``conversation_context`` (the refreshed context). A store
failure is swallowed because the response is already determined (R14.28 analogue).
"""

from datetime import UTC, datetime

from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.memory.store import ANALYTICS_INTENT_MAX_CHARS, TurnRecord

__all__ = ["make_conversation_context_update"]


def make_conversation_context_update(deps: NodeDeps):
    """Return the conversation_context_update node bound to ``deps``."""

    def node(state: TurnState, telemetry: TurnTelemetry) -> dict[str, object]:
        record = TurnRecord(
            user_message=state.raw_message,
            answer_text=state.answer_text or "",
            scope_decision=state.scope_decision or "IN_SCOPE",
            intent=state.intent or "REJECTED",
            analytics_intent_json=_serialize_intent(state),
            requested_at=state.turn_started_at,
            completed_at=datetime.now(UTC),
        )
        try:
            deps.store.append_turn(state.user_id, state.conversation_id, record)
            context = deps.store.get_context(state.user_id, state.conversation_id)
        except Exception:
            # The response already exists; a store failure must not change it.
            return {"conversation_context": list(state.conversation_context)}
        return {"conversation_context": list(context)}

    return node


def _serialize_intent(state: TurnState) -> str | None:
    """Serialize the analytics intent, omitting it when over the cap (R12.26-R12.27)."""
    if state.analytics_intent is None:
        return None
    serialized = state.analytics_intent.model_dump_json()
    if len(serialized) > ANALYTICS_INTENT_MAX_CHARS:
        return None
    return serialized
