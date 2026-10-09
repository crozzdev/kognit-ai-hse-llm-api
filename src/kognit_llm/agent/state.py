"""Graph state, outcome/category enumerations and the node write-map (R10.18-R10.33).

``TurnState`` carries exactly the 20 fields of R10.18 and forbids extras (D10:
observability data lives in ``TurnTelemetry``, not here). ``NODE_WRITES`` maps
each node to the state fields it may write (R10.19); ``WRITE_ONCE`` names the
fields written at most once (R10.20, R10.22). The guard enforces both.

``TurnOutcome`` has the 12 values of R10.33; ``ErrorCategory`` has the 8 values of
R14.11. The two enumerations differ by design: ``WAREHOUSE_TIMEOUT`` (an outcome)
maps to ``TIMEOUT`` (a category).
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kognit_llm.nlu.intent import AnalyticsIntent
from kognit_llm.safety.firewall import FirewallVerdict
from kognit_llm.schema.context_provider import SchemaContext
from kognit_llm.sqlgen.generator import GeneratedSQL

__all__ = [
    "NODE_WRITES",
    "WRITE_ONCE",
    "ErrorCategory",
    "TurnOutcome",
    "TurnState",
]


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


class TurnState(BaseModel):
    """The graph state for one chat turn: exactly the 20 fields of R10.18.

    ``result_set`` is held as an opaque object so this module needs no import
    from ``data/`` (the executor's ``ResultSet`` is passed through unchanged) and
    ``conversation_context`` holds opaque turn records; both are validated by the
    components that produce them, not re-validated here.
    """

    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, arbitrary_types_allowed=True
    )

    request_id: str
    conversation_id: str
    user_id: Literal["DEMO"] = "DEMO"
    raw_message: str
    turn_started_at: datetime
    conversation_context: list[object] = Field(default_factory=list)
    scope_decision: Literal["IN_SCOPE", "OUT_OF_SCOPE", "UNSAFE"] | None = None
    intent: (
        Literal["DATA_QUERY", "GENERAL_CHAT", "CLARIFICATION_NEEDED", "REJECTED"] | None
    ) = None
    analytics_intent: AnalyticsIntent | None = None
    schema_context: SchemaContext | None = None
    generated_sql: GeneratedSQL | None = None
    firewall_verdict: FirewallVerdict | None = None
    regeneration_count: int = 0
    result_set: object | None = None
    result_row_count: int | None = None
    query_duration_ms: int | None = None
    answer_text: str | None = None
    model_call_count: int = 0
    error_category: ErrorCategory | None = None
    turn_outcome: TurnOutcome | None = None


# Each node may write only the fields listed for it (R10.19).
NODE_WRITES: dict[str, frozenset[str]] = {
    "scope_validation": frozenset({"scope_decision"}),
    "intent_classification": frozenset(
        {"intent", "analytics_intent", "model_call_count"}
    ),
    "schema_context_selection": frozenset({"schema_context"}),
    "query_generation": frozenset(
        {"generated_sql", "regeneration_count", "model_call_count"}
    ),
    "query_validation": frozenset({"firewall_verdict"}),
    "query_execution": frozenset(
        {"result_set", "result_row_count", "query_duration_ms"}
    ),
    "answer_synthesis": frozenset({"answer_text", "model_call_count", "turn_outcome"}),
    "terminal_error": frozenset({"answer_text", "error_category", "turn_outcome"}),
    "conversation_context_update": frozenset({"conversation_context"}),
}

# Fields written at most once per turn (R10.20, R10.22).
WRITE_ONCE: frozenset[str] = frozenset({"scope_decision", "turn_outcome"})
