"""Turn-outcome and error-category enumerations for the agent workflow.

These two enumerations are defined here because both the HTTP error layer
(``api/errors.py``) and the graph (M-13) depend on them. The full ``TurnState``
model, ``NODE_WRITES`` map and ``WRITE_ONCE`` set are added by the LangGraph
milestone (M-13); this module currently carries only the enumerations they share.

``TurnOutcome`` has the 12 values of R10.33; ``ErrorCategory`` has the 8 values of
R14.11. The two enumerations differ by design: ``WAREHOUSE_TIMEOUT`` (an outcome)
maps to ``TIMEOUT`` (a category).
"""

from enum import StrEnum

__all__ = ["ErrorCategory", "TurnOutcome"]


class TurnOutcome(StrEnum):
    """The recorded outcome of one chat turn (R10.33)."""

    ANSWERED_DATA_QUERY = "ANSWERED_DATA_QUERY"
    ANSWERED_GENERAL_CHAT = "ANSWERED_GENERAL_CHAT"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    SCOPE_REJECTED = "SCOPE_REJECTED"
    INTENT_UNRESOLVED = "INTENT_UNRESOLVED"
    FIREWALL_REJECTED = "FIREWALL_REJECTED"
    WAREHOUSE_ERROR = "WAREHOUSE_ERROR"
    WAREHOUSE_TIMEOUT = "WAREHOUSE_TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TURN_TIMEOUT = "TURN_TIMEOUT"
    MODEL_CALL_LIMIT_REACHED = "MODEL_CALL_LIMIT_REACHED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorCategory(StrEnum):
    """The error category recorded on an error or rejection turn (R14.11)."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    SCOPE_REJECTED = "SCOPE_REJECTED"
    FIREWALL_REJECTED = "FIREWALL_REJECTED"
    INTENT_UNRESOLVED = "INTENT_UNRESOLVED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    WAREHOUSE_ERROR = "WAREHOUSE_ERROR"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
