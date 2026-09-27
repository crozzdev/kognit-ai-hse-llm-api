"""LangGraph turn graph assembly (R10.1-R10.17, R10.23).

``build_graph(deps)`` compiles the fixed nine-node ``StateGraph`` from the
module-level ``PERMITTED_EDGES`` inventory, with the single regeneration cycle
(``query_validation`` -> ``query_generation``) as the only loop (R10.16). Routing
decisions read only the validated state, never model output (R10.14). The
compiled graph is built once per execution environment; per-turn telemetry is
threaded through ``guard.CURRENT_TELEMETRY``.
"""

from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from kognit_llm.agent.guard import guarded
from kognit_llm.agent.nodes.answer_synthesis import make_answer_synthesis
from kognit_llm.agent.nodes.conversation_context_update import (
    make_conversation_context_update,
)
from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.nodes.intent_classification import make_intent_classification
from kognit_llm.agent.nodes.query_execution import make_query_execution
from kognit_llm.agent.nodes.query_generation import make_query_generation
from kognit_llm.agent.nodes.query_validation import make_query_validation
from kognit_llm.agent.nodes.schema_context_selection import (
    make_schema_context_selection,
)
from kognit_llm.agent.nodes.scope_validation import make_scope_validation
from kognit_llm.agent.nodes.terminal_error import make_terminal_error
from kognit_llm.agent.state import TurnState

__all__ = ["PERMITTED_EDGES", "build_graph"]

# The complete permitted-edge inventory (R10.13). Conditional edges are listed
# once per (source, target); the router picks the target from validated state.
PERMITTED_EDGES: frozenset[tuple[str, str]] = frozenset(
    {
        ("__start__", "scope_validation"),
        ("scope_validation", "intent_classification"),
        ("scope_validation", "terminal_error"),
        ("intent_classification", "schema_context_selection"),
        ("intent_classification", "answer_synthesis"),
        ("intent_classification", "terminal_error"),
        ("schema_context_selection", "query_generation"),
        ("schema_context_selection", "terminal_error"),
        ("query_generation", "query_validation"),
        ("query_generation", "terminal_error"),
        ("query_validation", "query_execution"),
        ("query_validation", "query_generation"),
        ("query_validation", "terminal_error"),
        ("query_execution", "answer_synthesis"),
        ("query_execution", "terminal_error"),
        ("answer_synthesis", "conversation_context_update"),
        ("answer_synthesis", "terminal_error"),
        ("terminal_error", "conversation_context_update"),
        ("conversation_context_update", "__end__"),
    }
)


def build_graph(deps: NodeDeps):
    """Compile the turn graph once for an execution environment (R10.1)."""
    graph: StateGraph = StateGraph(TurnState)

    def add(name: str, node: Callable[[TurnState], dict[str, object]]) -> None:
        # langgraph's add_node type union does not describe a plain state->update
        # callable precisely; the runtime accepts it, so cast for the checker.
        graph.add_node(name, cast(Any, node))

    add("scope_validation", guarded("scope_validation", make_scope_validation(deps)))
    add(
        "intent_classification",
        guarded("intent_classification", make_intent_classification(deps)),
    )
    add(
        "schema_context_selection",
        guarded("schema_context_selection", make_schema_context_selection(deps)),
    )
    add("query_generation", guarded("query_generation", make_query_generation(deps)))
    add("query_validation", guarded("query_validation", make_query_validation(deps)))
    add("query_execution", guarded("query_execution", make_query_execution(deps)))
    add("answer_synthesis", guarded("answer_synthesis", make_answer_synthesis(deps)))
    add("terminal_error", guarded("terminal_error", make_terminal_error(deps)))
    add(
        "conversation_context_update",
        guarded("conversation_context_update", make_conversation_context_update(deps)),
    )

    graph.add_edge(START, "scope_validation")
    graph.add_conditional_edges(
        "scope_validation",
        _route_after_scope,
        {
            "intent_classification": "intent_classification",
            "terminal_error": "terminal_error",
        },
    )
    graph.add_conditional_edges(
        "intent_classification",
        _route_after_intent,
        {
            "schema_context_selection": "schema_context_selection",
            "answer_synthesis": "answer_synthesis",
            "terminal_error": "terminal_error",
        },
    )
    graph.add_conditional_edges(
        "schema_context_selection",
        _route_after_schema,
        {"query_generation": "query_generation", "terminal_error": "terminal_error"},
    )
    graph.add_edge("query_generation", "query_validation")
    graph.add_conditional_edges(
        "query_validation",
        _route_after_validation,
        {
            "query_execution": "query_execution",
            "query_generation": "query_generation",
            "terminal_error": "terminal_error",
        },
    )
    graph.add_conditional_edges(
        "query_execution",
        _route_after_execution,
        {"answer_synthesis": "answer_synthesis", "terminal_error": "terminal_error"},
    )
    graph.add_conditional_edges(
        "answer_synthesis",
        _route_after_synthesis,
        {
            "conversation_context_update": "conversation_context_update",
            "terminal_error": "terminal_error",
        },
    )
    graph.add_edge("terminal_error", "conversation_context_update")
    graph.add_edge("conversation_context_update", END)

    return graph.compile()


# ── Routers: read validated state only, never model output (R10.14) ───────────


def _route_after_scope(state: TurnState) -> str:
    if state.scope_decision == "IN_SCOPE":
        return "intent_classification"
    return "terminal_error"


def _route_after_intent(state: TurnState) -> str:
    if state.error_category is not None:
        return "terminal_error"
    if state.intent == "DATA_QUERY":
        return "schema_context_selection"
    if state.intent == "GENERAL_CHAT":
        return "answer_synthesis"
    return "terminal_error"


def _route_after_schema(state: TurnState) -> str:
    if state.error_category is not None or state.schema_context is None:
        return "terminal_error"
    return "query_generation"


def _route_after_validation(state: TurnState) -> str:
    verdict = state.firewall_verdict
    if verdict is not None and verdict.verdict == "ADMIT":
        return "query_execution"
    # First REJECT (count 0): regenerate once; second REJECT: terminal (R10.13, R10.17).
    if state.regeneration_count == 0:
        return "query_generation"
    return "terminal_error"


def _route_after_execution(state: TurnState) -> str:
    if state.error_category is not None or state.result_set is None:
        return "terminal_error"
    return "answer_synthesis"


def _route_after_synthesis(state: TurnState) -> str:
    if state.error_category is not None or state.answer_text is None:
        return "terminal_error"
    return "conversation_context_update"
