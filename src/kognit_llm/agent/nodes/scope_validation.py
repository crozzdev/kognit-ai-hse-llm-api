"""scope_validation node: HSE scope decision (R2.1-R2.17).

Runs the deterministic scope stage first (0 model calls) and, only when it
matches no rejection category, one model-assisted classification call. Writes
``scope_decision`` (R10.19). The single model call is wired to the provider here;
``safety.scope_guard`` stays provider-free (import boundary B1).
"""

from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.providers.base import (
    CompletionRequest,
    Message,
    ProviderError,
)
from kognit_llm.safety.scope_guard import ScopeVerdict, decide

__all__ = ["make_scope_validation"]

_SYSTEM = (
    "Classify the user message for an HSE analytics assistant. Reply with a JSON "
    'object {"decision": one of IN_SCOPE, OUT_OF_SCOPE, UNSAFE}. '
    "Respond with the JSON object only: no explanation, no reasoning, no markdown, "
    "no code fences, no text before or after the object."
)


def make_scope_validation(deps: NodeDeps):
    """Return the scope_validation node bound to ``deps``."""

    def classify(message: str) -> dict[str, object] | None:
        request = CompletionRequest[ScopeVerdict](
            call_type="scope",
            system_instruction=_SYSTEM,
            messages=(Message(role="user", content=message),),
            output_model=ScopeVerdict,
            temperature=deps.settings.model_temperature,
            max_output_tokens=deps.settings.model_max_output_tokens,
            timeout_ms=deps.settings.model_timeout_ms,
            request_id="",
        )
        try:
            result = deps.provider.complete(request)
        except ProviderError:
            return None
        return {"decision": result.output.decision}

    def node(state: TurnState, telemetry: TurnTelemetry) -> dict[str, object]:
        result = decide(state.raw_message, classify)
        if result.model_called:
            telemetry.record_provider_call("scope", 0, 0)
        return {"scope_decision": result.decision}

    return node
