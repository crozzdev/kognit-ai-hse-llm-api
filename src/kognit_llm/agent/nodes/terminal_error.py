"""terminal_error node: the single error sink before context update (R10.32).

Sets ``answer_text``, ``error_category`` and ``turn_outcome`` from whatever
terminal condition routed here, choosing a fixed per-category user message with
no diagnostics (R2.12, R9.8, R10.32). ``turn_outcome`` keeps any value a prior
node already wrote (R10.22).
"""

from typing import Literal

from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import ErrorCategory, TurnOutcome, TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.answer import templates

__all__ = ["make_terminal_error"]

Language = Literal["es", "en"]


def make_terminal_error(deps: NodeDeps):
    """Return the terminal_error node bound to ``deps``."""

    def node(state: TurnState, telemetry: TurnTelemetry) -> dict[str, object]:
        language: Literal["es", "en"] = (
            "es" if _looks_spanish(state.raw_message) else "en"
        )
        outcome, category, message = _classify_terminal(state, language)
        update: dict[str, object] = {"answer_text": message, "error_category": category}
        # turn_outcome is write-once (R10.22): only set it if not already set.
        if state.turn_outcome is None:
            update["turn_outcome"] = outcome
        return update

    return node


def _classify_terminal(
    state: TurnState, language: Language
) -> tuple[TurnOutcome, ErrorCategory | None, str]:
    """Map the routed terminal condition to (outcome, category, user message)."""
    if state.scope_decision in ("OUT_OF_SCOPE", "UNSAFE"):
        return (
            TurnOutcome.SCOPE_REJECTED,
            ErrorCategory.SCOPE_REJECTED,
            templates.rejection(language),
        )
    if state.intent == "CLARIFICATION_NEEDED":
        return (
            TurnOutcome.CLARIFICATION_REQUESTED,
            None,
            templates.clarification("", language),
        )
    if state.firewall_verdict is not None and state.firewall_verdict.verdict == (
        "REJECT"
    ):
        return (
            TurnOutcome.FIREWALL_REJECTED,
            ErrorCategory.FIREWALL_REJECTED,
            _could_not_answer_safely(language),
        )
    if state.intent == "REJECTED":
        return (
            TurnOutcome.INTENT_UNRESOLVED,
            ErrorCategory.INTENT_UNRESOLVED,
            _could_not_interpret(language),
        )
    return (
        TurnOutcome.INTERNAL_ERROR,
        ErrorCategory.INTERNAL_ERROR,
        _could_not_complete(language),
    )


def _could_not_answer_safely(language: Language) -> str:
    if language == "es":
        return "No pude responder esa pregunta de forma segura."
    return "I could not answer that question safely."


def _could_not_interpret(language: Language) -> str:
    if language == "es":
        return "No pude interpretar esa pregunta."
    return "I could not interpret that question."


def _could_not_complete(language: Language) -> str:
    if language == "es":
        return "No pude completar la solicitud."
    return "The request could not be completed."


def _looks_spanish(message: str) -> bool:
    lowered = message.lower()
    return any(ch in message for ch in "ñáéíóú¿¡") or any(
        word in lowered for word in (" el ", " la ", "cuant", "planta")
    )
