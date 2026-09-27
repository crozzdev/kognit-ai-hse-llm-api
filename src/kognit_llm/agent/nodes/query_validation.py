"""query_validation node: deny-by-default firewall verdict (R6, R6.2).

Runs the non-LLM firewall on the generated statement with **zero** model calls
and writes ``firewall_verdict``. The graph routes an ``ADMIT`` to execution, a
first ``REJECT`` back to generation (one regeneration), and a second ``REJECT``
to ``terminal_error`` (R10.13).
"""

from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import TurnState
from kognit_llm.agent.telemetry import TurnTelemetry
from kognit_llm.safety.firewall import FirewallLimits, validate_sql

__all__ = ["make_query_validation"]


def make_query_validation(deps: NodeDeps):
    """Return the query_validation node bound to ``deps``."""
    limits = FirewallLimits(
        row_cap=deps.settings.row_cap,
        max_statement_chars=deps.settings.max_statement_chars,
        max_join_count=deps.settings.max_join_count,
        max_subquery_depth=deps.settings.max_subquery_depth,
        max_set_operation_arms=deps.settings.max_set_operation_arms,
    )

    def node(state: TurnState, telemetry: TurnTelemetry) -> dict[str, object]:
        generated = state.generated_sql
        if generated is None:
            raise ValueError("query_validation requires a generated statement")
        verdict = validate_sql(
            generated.statement,
            generated.params,
            allowlist=deps.allowlist,
            functions=deps.allowlist.functions,
            limits=limits,
            approved_schema=deps.settings.db_schema,
            user_message=state.raw_message,
        )
        return {"firewall_verdict": verdict}

    return node
