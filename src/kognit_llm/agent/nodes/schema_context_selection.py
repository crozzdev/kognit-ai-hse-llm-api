"""schema_context_selection node: allow-list-scoped schema context (R4.8-R4.30).

Selects the tables/columns the analytics intent references plus join keys, within
the token budget, with 0 model calls. Writes ``schema_context``. Budget
exhaustion after all reductions yields no context, which routes the turn to
``terminal_error`` with ``INTERNAL_ERROR`` (R4.30).
"""

from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.schema.context_provider import build_schema_context

__all__ = ["make_schema_context_selection"]


def make_schema_context_selection(deps: NodeDeps):
    """Return the schema_context_selection node bound to ``deps``."""

    def node(state: TurnState, telemetry: TurnTelemetry) -> dict[str, object]:
        intent = state.analytics_intent
        if intent is None:
            raise ValueError("schema_context_selection requires an analytics intent")

        tables, columns = _referenced(intent)
        context = build_schema_context(
            referenced_tables=tables,
            referenced_columns=columns,
            token_budget=deps.settings.schema_context_token_budget,
            include_dimension_values=deps.settings.include_dimension_values,
            dimension_value_max=deps.settings.dimension_value_max,
            allowlist=deps.allowlist,
        )
        return {"schema_context": context}

    return node


def _referenced(intent) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Derive referenced tables/columns from the intent's attributes and filters."""
    columns: dict[str, set[str]] = {"fact_incidents": {"record_no"}}
    if intent.measure == "action_count":
        columns.setdefault("fact_actions", set()).add("record_no")

    def note(attribute: str) -> None:
        if "." in attribute:
            table, column = attribute.split(".", 1)
            columns.setdefault(table, set()).add(column)

    for attr in intent.grouping_attributes:
        note(attr)
    for filt in intent.filters:
        note(filt.attribute)
    # A date filter always touches dim_date.
    columns.setdefault("dim_date", set()).add("date")

    frozen = {table: tuple(sorted(cols)) for table, cols in columns.items()}
    return tuple(frozen), frozen


__all__ = ["make_schema_context_selection"]
