"""Unit tests for the answer_synthesis node (src/kognit_llm/agent/nodes).

Cover both turn paths without any network or warehouse access:
- GENERAL_CHAT: model answer, empty-output fallback, provider-failure fallback.
- DATA_QUERY: deterministic single-row template (zero model calls), the
  fidelity-backed draft loop (draft accepted, draft rejected -> template
  fallback, two-call cap, provider failure mid-loop), and the measure/language
  selection and missing-state guard.

The provider is a hand-rolled fake implementing the ``ModelProvider`` protocol;
``deps`` carries ``None`` for the executor/store/allowlist the node never uses.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import BaseModel

from kognit_llm.agent.nodes.answer_synthesis import make_answer_synthesis
from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import TurnOutcome, TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.answer import templates
from kognit_llm.config.settings import Settings, settings_from_mapping
from kognit_llm.data.executor import ResultSet, WarehouseExecutor
from kognit_llm.memory.store import ConversationStore
from kognit_llm.nlu.dates import TimeRange
from kognit_llm.nlu.intent import AnalyticsIntent, Measure
from kognit_llm.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderError,
    RetryableProviderError,
)
from kognit_llm.schema.allowlist import AllowList

_START = date(2026, 1, 1)
_END = date(2026, 1, 31)


@dataclass
class _FakeProvider:
    """A ModelProvider whose ``complete`` is scripted per call.

    ``replies`` is a list of either a string (returned as the draft ``text``) or
    an exception instance (raised). Each ``complete`` consumes the next entry;
    calls are recorded for assertions.
    """

    provider_id: str = "fake"
    replies: list[object] = field(default_factory=list)
    requests: list[CompletionRequest[Any]] = field(default_factory=list)

    def complete(
        self, request: CompletionRequest[Any]
    ) -> CompletionResult[BaseModel]:
        self.requests.append(request)
        if not self.replies:
            raise AssertionError("unexpected extra provider call")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        output = request.output_model(text=reply)
        return CompletionResult(
            output=output,
            prompt_tokens=11,
            completion_tokens=7,
            finish_reason="COMPLETED",
        )


def _settings(**overrides: object) -> Settings:
    base = settings_from_mapping({})
    return base.model_copy(update=overrides) if overrides else base


def _deps(provider: _FakeProvider, **settings_overrides: object) -> NodeDeps:
    # The executor, store and allowlist are never touched by this node; cast
    # ``None`` to the declared interfaces so the bundle type-checks.
    return NodeDeps(
        settings=_settings(**settings_overrides),
        provider=provider,
        executor=cast(WarehouseExecutor, None),
        store=cast(ConversationStore, None),
        allowlist=cast(AllowList, None),
    )


def _state(**overrides: object) -> TurnState:
    base = TurnState(
        request_id="req-1",
        conversation_id="conv-1",
        raw_message="How many incidents last month?",
        turn_started_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    return base.model_copy(update=overrides) if overrides else base


def _intent(measure: Measure = "incident_count") -> AnalyticsIntent:
    return AnalyticsIntent(
        measure=measure,
        time_range=TimeRange(start_date=_START, end_date=_END),
        limit=1000,
        confidence=Decimal("0.90"),
    )


def _run(
    deps: NodeDeps, state: TurnState
) -> tuple[dict[str, object], TurnTelemetry]:
    telemetry = TurnTelemetry()
    node = make_answer_synthesis(deps)
    return node(state, telemetry), telemetry


# ── GENERAL_CHAT path ─────────────────────────────────────────────────────────


def test_general_chat_uses_model_answer():
    provider = _FakeProvider(replies=["HSE means Health, Safety and Environment."])
    deps = _deps(provider)
    state = _state(intent="GENERAL_CHAT", raw_message="what is HSE?")

    result, telemetry = _run(deps, state)

    assert result["answer_text"] == "HSE means Health, Safety and Environment."
    assert result["turn_outcome"] == TurnOutcome.ANSWERED_GENERAL_CHAT
    assert result["model_call_count"] == 1
    assert telemetry.provider_calls == {"answer": 1}


def test_general_chat_empty_output_falls_back_to_capabilities():
    provider = _FakeProvider(replies=["   "])
    deps = _deps(provider)
    state = _state(intent="GENERAL_CHAT")

    result, _ = _run(deps, state)

    assert result["answer_text"] == templates.capabilities("es")
    # The model was still called, so the count advances.
    assert result["model_call_count"] == 1


def test_general_chat_provider_failure_falls_back_without_counting_call():
    provider = _FakeProvider(replies=[ProviderError("down")])
    deps = _deps(provider)
    state = _state(intent="GENERAL_CHAT")

    result, telemetry = _run(deps, state)

    assert result["answer_text"] == templates.capabilities("es")
    assert result["model_call_count"] == 0
    assert telemetry.provider_calls == {}


# ── DATA_QUERY path ───────────────────────────────────────────────────────────


def test_data_query_single_row_uses_template_with_no_model_call():
    provider = _FakeProvider(replies=[])  # must not be called
    deps = _deps(provider)
    result_set = ResultSet(
        columns=("incident_count",),
        rows=((Decimal("42"),),),
        truncated=False,
        duration_ms=3,
    )
    state = _state(
        intent="DATA_QUERY",
        analytics_intent=_intent(),
        result_set=result_set,
    )

    result, telemetry = _run(deps, state)

    expected = templates.single_aggregate(
        Decimal("42"), "incidentes", _START, _END, "es"
    )
    assert result["answer_text"] == expected
    assert result["turn_outcome"] == TurnOutcome.ANSWERED_DATA_QUERY
    assert result["model_call_count"] == 0
    assert telemetry.provider_calls == {}


def test_data_query_multi_row_accepts_faithful_draft():
    # Draft contains only permitted numbers (the two counts and the period).
    draft_text = "During January 2026: Plant A: 10; Plant B: 5."
    provider = _FakeProvider(replies=[draft_text])
    deps = _deps(provider, answer_language="en")
    result_set = ResultSet(
        columns=("plant", "incident_count"),
        rows=(("Plant A", Decimal("10")), ("Plant B", Decimal("5"))),
        truncated=False,
        duration_ms=4,
    )
    state = _state(
        intent="DATA_QUERY",
        analytics_intent=_intent(),
        result_set=result_set,
    )

    result, telemetry = _run(deps, state)

    assert result["answer_text"] == draft_text
    assert result["model_call_count"] == 1
    assert telemetry.provider_calls == {"answer": 1}
    # English selected via settings, reflected in the draft instruction.
    assert "English" in provider.requests[0].system_instruction


def test_data_query_rejected_draft_falls_back_to_grouped_template():
    # Draft injects an unpermitted number (999) -> fidelity rejects both drafts,
    # the loop stops at the two-call cap and the deterministic template is used.
    bad_draft = "During the period: Plant A: 999 incidents."
    provider = _FakeProvider(replies=[bad_draft, bad_draft])
    deps = _deps(provider, answer_language="en")
    result_set = ResultSet(
        columns=("plant", "incident_count"),
        rows=(("Plant A", Decimal("10")), ("Plant B", Decimal("5"))),
        truncated=False,
        duration_ms=4,
    )
    state = _state(
        intent="DATA_QUERY",
        analytics_intent=_intent(),
        result_set=result_set,
    )

    result, _ = _run(deps, state)

    expected = templates.grouped(
        [("Plant A", Decimal("10")), ("Plant B", Decimal("5"))],
        _START,
        _END,
        "en",
    )
    assert result["answer_text"] == expected
    # Two drafts attempted (cap), then the template fallback.
    assert result["model_call_count"] == 2


def test_data_query_draft_loop_stops_at_two_calls():
    # Provider would supply a third bad draft, but the loop must stop at two.
    bad = "Plant A: 999."
    provider = _FakeProvider(replies=[bad, bad, bad])
    deps = _deps(provider, answer_language="en")
    result_set = ResultSet(
        columns=("plant", "incident_count"),
        rows=(("Plant A", Decimal("10")), ("Plant B", Decimal("5"))),
        truncated=False,
        duration_ms=4,
    )
    state = _state(
        intent="DATA_QUERY",
        analytics_intent=_intent(),
        result_set=result_set,
    )

    result, telemetry = _run(deps, state)

    assert result["model_call_count"] == 2
    assert telemetry.provider_calls == {"answer": 2}
    # The third scripted reply is left unconsumed.
    assert provider.replies == [bad]


def test_data_query_provider_failure_mid_loop_falls_back():
    # Both draft attempts fail at the provider; the loop tries twice (R9.13).
    provider = _FakeProvider(
        replies=[RetryableProviderError("timeout"), RetryableProviderError("timeout")]
    )
    deps = _deps(provider, answer_language="en")
    result_set = ResultSet(
        columns=("plant", "incident_count"),
        rows=(("Plant A", Decimal("10")), ("Plant B", Decimal("5"))),
        truncated=False,
        duration_ms=4,
    )
    state = _state(
        intent="DATA_QUERY",
        analytics_intent=_intent(),
        result_set=result_set,
    )

    result, _ = _run(deps, state)

    expected = templates.grouped(
        [("Plant A", Decimal("10")), ("Plant B", Decimal("5"))],
        _START,
        _END,
        "en",
    )
    assert result["answer_text"] == expected
    # The failed call returned None without incrementing the count.
    assert result["model_call_count"] == 0


def test_data_query_measure_label_selected_per_measure():
    provider = _FakeProvider(replies=[])
    deps = _deps(provider)
    result_set = ResultSet(
        columns=("action_count",),
        rows=((Decimal("7"),),),
        truncated=False,
        duration_ms=2,
    )
    state = _state(
        intent="DATA_QUERY",
        analytics_intent=_intent("action_count"),
        result_set=result_set,
    )

    result, _ = _run(deps, state)

    expected = templates.single_aggregate(
        Decimal("7"), "acciones correctivas", _START, _END, "es"
    )
    assert result["answer_text"] == expected


def test_data_query_missing_state_raises():
    deps = _deps(_FakeProvider(replies=[]))
    state = _state(intent="DATA_QUERY", analytics_intent=None, result_set=None)

    node = make_answer_synthesis(deps)
    with pytest.raises(ValueError, match="requires intent and a result set"):
        node(state, TurnTelemetry())


# ── Language selection ─────────────────────────────────────────────────────────


def test_language_auto_detects_spanish_from_message():
    provider = _FakeProvider(replies=["Respuesta en espanol."])
    deps = _deps(provider, answer_language="auto")
    state = _state(intent="GENERAL_CHAT", raw_message="¿Cuántos incidentes hubo?")

    _run(deps, state)

    assert "Spanish" in provider.requests[0].system_instruction


def test_language_auto_defaults_to_english_for_plain_ascii():
    provider = _FakeProvider(replies=["Answer in English."])
    deps = _deps(provider, answer_language="auto")
    state = _state(intent="GENERAL_CHAT", raw_message="what can you do?")

    _run(deps, state)

    assert "English" in provider.requests[0].system_instruction
