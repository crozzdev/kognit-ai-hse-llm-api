"""answer_synthesis node: natural-language answer (R9.1-R9.30, R8.34, R9.11).

For a GENERAL_CHAT turn, emits the capabilities answer with no warehouse query.
For a DATA_QUERY turn, synthesizes from the result set with the fidelity-backed
template path (0-2 model calls). Writes ``answer_text``, ``model_call_count`` and
``turn_outcome``.
"""

from typing import Literal, cast

from pydantic import BaseModel

from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import TurnOutcome, TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.answer import templates
from kognit_llm.answer.synthesizer import SynthesisInput, synthesize
from kognit_llm.data.executor import ResultSet
from kognit_llm.providers.base import (
    CompletionRequest,
    Message,
    ProviderError,
    ProviderOutputError,
)

__all__ = ["make_answer_synthesis"]

_MEASURE_LABELS = {
    "incident_count": {"es": "incidentes", "en": "incidents"},
    "severity_index": {"es": "indice de severidad", "en": "severity index"},
    "action_count": {"es": "acciones correctivas", "en": "corrective actions"},
}


class _DraftOut(BaseModel):
    text: str


def make_answer_synthesis(deps: NodeDeps):
    """Return the answer_synthesis node bound to ``deps``."""

    def node(state: TurnState, telemetry: TurnTelemetry) -> dict[str, object]:
        language = _language(deps, state.raw_message)

        if state.intent == "GENERAL_CHAT":
            return {
                "answer_text": templates.capabilities(language),
                "model_call_count": state.model_call_count,
                "turn_outcome": TurnOutcome.ANSWERED_GENERAL_CHAT,
            }

        intent = state.analytics_intent
        result = cast(ResultSet | None, state.result_set)
        if intent is None or result is None:
            raise ValueError("answer_synthesis requires intent and a result set")

        calls = [state.model_call_count]

        def draft(_: str) -> str | None:
            if calls[0] - state.model_call_count >= 2:
                return None
            request = CompletionRequest[_DraftOut](
                call_type="answer",
                system_instruction=(
                    "Answer the HSE analytics question faithfully. Respond with the "
                    "JSON object only: no explanation, no reasoning, no markdown, no "
                    "code fences, no text before or after the object."
                ),
                messages=(Message(role="user", content=state.raw_message),),
                output_model=_DraftOut,
                temperature=deps.settings.model_temperature,
                max_output_tokens=deps.settings.model_max_output_tokens,
                timeout_ms=deps.settings.model_timeout_ms,
                request_id=state.request_id,
            )
            try:
                completion = deps.provider.complete(request)
            except (ProviderError, ProviderOutputError):
                return None
            calls[0] += 1
            telemetry.record_provider_call(
                "answer", completion.prompt_tokens, completion.completion_tokens
            )
            return completion.output.text

        data = SynthesisInput(
            columns=result.columns,
            rows=result.rows,
            truncated=result.truncated,
            measure_label=_MEASURE_LABELS[intent.measure][language],
            start=intent.time_range.start_date,
            end=intent.time_range.end_date,
            row_cap=deps.settings.row_cap,
            language=language,
        )
        answer = synthesize(data, draft)
        return {
            "answer_text": answer,
            "model_call_count": calls[0],
            "turn_outcome": TurnOutcome.ANSWERED_DATA_QUERY,
        }

    return node


def _language(deps: NodeDeps, message: str) -> Literal["es", "en"]:
    configured = deps.settings.answer_language
    if configured == "es" or configured == "en":
        return configured
    # auto: a light heuristic; Spanish diacritics or common words -> es.
    lowered = message.lower()
    if any(ch in message for ch in "ñáéíóú¿¡") or any(
        word in lowered for word in (" el ", " la ", "cuant", "cuál", "planta")
    ):
        return "es"
    return "en"
