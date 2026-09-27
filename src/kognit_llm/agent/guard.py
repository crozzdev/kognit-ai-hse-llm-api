"""Node guard: entry/exit validation and write-map enforcement (R10.19-R10.22, R10.32).

``guarded`` wraps a node function so that:
- The returned update's keys are a subset of ``NODE_WRITES[node]`` (R10.19).
- A write to a ``WRITE_ONCE`` field that already holds a value is rejected
  (``scope_decision`` R10.20, ``turn_outcome`` first-write-wins R10.22).
- Any violation, or an unhandled exception in the node, is turned into a routed
  transition to ``terminal_error`` with ``turn_outcome = INTERNAL_ERROR`` (R10.32).
- The node's elapsed time is recorded into ``TurnTelemetry`` (R16.16-R16.17).

A node function has the signature ``(state, telemetry) -> dict[str, object]`` and
returns only the fields it writes; the guard applies the update to the state.
"""

import time
from collections.abc import Callable
from contextvars import ContextVar

from kognit_llm.agent.state import (
    NODE_WRITES,
    WRITE_ONCE,
    ErrorCategory,
    TurnOutcome,
    TurnState,
)
from kognit_llm.agent.telemetry import TurnTelemetry

__all__ = ["CURRENT_TELEMETRY", "GuardViolation", "guarded"]

NodeFn = Callable[[TurnState, TurnTelemetry], dict[str, object]]

# Per-turn telemetry is threaded through this context variable rather than through
# TurnState (D10), so one compiled graph can serve every turn while each turn's
# node timings and token counts stay isolated.
CURRENT_TELEMETRY: ContextVar[TurnTelemetry] = ContextVar("current_telemetry")


class GuardViolation(Exception):
    """Raised internally when a node writes outside its contract (R10.20-R10.21)."""


def guarded(node_name: str, fn: NodeFn) -> Callable[[TurnState], dict[str, object]]:
    """Wrap ``fn`` into a LangGraph node returning a validated update dict.

    On any contract violation or unhandled exception the wrapper returns an
    update routing to ``terminal_error`` with ``INTERNAL_ERROR`` rather than
    raising, so the graph always reaches a terminal path (R10.32). The node's
    elapsed time is recorded into the current turn's telemetry (R16.16-R16.17).
    """
    allowed = NODE_WRITES.get(node_name, frozenset())

    def wrapper(state: TurnState) -> dict[str, object]:
        telemetry = CURRENT_TELEMETRY.get()
        started = time.monotonic()
        try:
            update = fn(state, telemetry)
            _validate_update(node_name, update, allowed, state)
        except Exception:
            update = _internal_error_update(state)
        finally:
            telemetry.record_stage(
                node_name, int((time.monotonic() - started) * 1000)
            )
        return update

    return wrapper


def _validate_update(
    node_name: str,
    update: dict[str, object],
    allowed: frozenset[str],
    state: TurnState,
) -> None:
    extra = set(update) - allowed
    if extra:
        raise GuardViolation(
            f"node '{node_name}' wrote fields outside its contract: {sorted(extra)}"
        )
    for field_name in update:
        if field_name in WRITE_ONCE and getattr(state, field_name) is not None:
            # turn_outcome keeps its first value; scope_decision cannot be rewritten.
            raise GuardViolation(
                f"node '{node_name}' rewrote write-once field '{field_name}'"
            )


def _internal_error_update(state: TurnState) -> dict[str, object]:
    """Update routing to terminal_error with INTERNAL_ERROR, preserving turn_outcome."""
    update: dict[str, object] = {"error_category": ErrorCategory.INTERNAL_ERROR}
    if state.turn_outcome is None:
        update["turn_outcome"] = TurnOutcome.INTERNAL_ERROR
    return update
