"""query_generation node: one parameterized statement per intent (R5.1-R5.35).

Issues one model call for a ``GeneratedSQL`` from the schema context, intent and
few-shot pairs. Writes ``generated_sql``, ``regeneration_count`` and
``model_call_count``. On a regeneration attempt (after a firewall REJECT) it
requests a fresh statement, capped at two attempts per turn (R5.34).
"""

from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.providers.base import (
    CompletionRequest,
    Message,
    ProviderError,
)
from kognit_llm.sqlgen.generator import GeneratedSQL, build_generation_messages
from kognit_llm.sqlgen.prompts import SQL_SYSTEM_INSTRUCTION

__all__ = ["make_query_generation"]


def make_query_generation(deps: NodeDeps):
    """Return the query_generation node bound to ``deps``."""

    def node(state: TurnState, telemetry: TurnTelemetry) -> dict[str, object]:
        intent = state.analytics_intent
        context = state.schema_context
        if intent is None or context is None:
            raise ValueError("query_generation requires intent and schema context")

        # A prior REJECT verdict in state means this is the regeneration attempt.
        is_regeneration = (
            state.firewall_verdict is not None
            and state.firewall_verdict.verdict == "REJECT"
        )
        next_regeneration_count = (
            state.regeneration_count + 1
            if is_regeneration
            else state.regeneration_count
        )
        # On regeneration, reduce the examples to sharpen the retry (R4.29 spirit).
        example_limit = 1 if is_regeneration else None
        schema_block, intent_block = build_generation_messages(
            intent, context, example_limit=example_limit
        )
        request = CompletionRequest[GeneratedSQL](
            call_type="sql",
            system_instruction=SQL_SYSTEM_INSTRUCTION,
            messages=(
                Message(role="user", content=schema_block),
                Message(role="user", content=intent_block),
            ),
            output_model=GeneratedSQL,
            temperature=deps.settings.model_temperature,
            max_output_tokens=deps.settings.model_max_output_tokens,
            timeout_ms=deps.settings.model_timeout_ms,
            request_id=state.request_id,
        )
        try:
            result = deps.provider.complete(request)
        except ProviderError as err:
            raise RuntimeError("provider failed during query generation") from err
        telemetry.record_provider_call(
            "sql", result.prompt_tokens, result.completion_tokens
        )
        return {
            "generated_sql": result.output,
            "regeneration_count": next_regeneration_count,
            "model_call_count": state.model_call_count + 1,
        }

    return node
