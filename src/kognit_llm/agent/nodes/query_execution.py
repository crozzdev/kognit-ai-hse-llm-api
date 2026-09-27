"""query_execution node: read-only warehouse execution (R7.1-R7.13, R2.1).

Executes the admitted statement through the executor, which re-verifies the
firewall hash before running (R6.45). Writes ``result_set``, ``result_row_count``
and ``query_duration_ms``. A warehouse failure raises so the guard routes to
``terminal_error`` with a warehouse outcome. Execution is entered only after an
``IN_SCOPE`` decision and an ``ADMIT`` verdict (R2.1, R10.3).
"""

from kognit_llm.agent.nodes.deps import NodeDeps
from kognit_llm.agent.state import TurnState
from kognit_llm.agent.telemetry import TurnTelemetry

__all__ = ["make_query_execution"]


def make_query_execution(deps: NodeDeps):
    """Return the query_execution node bound to ``deps``."""

    def node(state: TurnState, telemetry: TurnTelemetry) -> dict[str, object]:
        generated = state.generated_sql
        verdict = state.firewall_verdict
        if generated is None or verdict is None:
            raise ValueError("query_execution requires generated SQL and a verdict")

        result = deps.executor.execute_admitted(
            generated.statement, generated.params, verdict
        )
        telemetry.result_truncated = result.truncated
        return {
            "result_set": result,
            "result_row_count": len(result.rows),
            "query_duration_ms": result.duration_ms,
        }

    return node
