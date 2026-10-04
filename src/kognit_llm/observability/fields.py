"""Closed log-field set and environment vocabulary mapping (R14.38, R14.26).

``LOG_FIELDS`` is the complete, closed set of field names a request log entry may
contain (R14.38); the logger emits no field outside it. ``ENVIRONMENT_LOG_VALUE``
maps the R15 configuration environment vocabulary (``local`` / ``ci`` / ``aws``)
to the R14.26 log identity vocabulary (``local`` / ``dev`` / ``prod``).
"""

__all__ = ["ENVIRONMENT_LOG_VALUE", "LOG_FIELDS", "STAGE_FIELDS"]

# The eight per-stage duration fields of R16.17 (one per traversed node).
STAGE_FIELDS: frozenset[str] = frozenset(
    {
        "stage_scope_validation_ms",
        "stage_intent_classification_ms",
        "stage_schema_context_selection_ms",
        "stage_query_generation_ms",
        "stage_query_validation_ms",
        "stage_query_execution_ms",
        "stage_answer_synthesis_ms",
        "stage_conversation_context_update_ms",
    }
)

# The complete closed field set of R14.38; no other field name may appear.
LOG_FIELDS: frozenset[str] = (
    frozenset(
        {
            "request_id",
            "correlation_id",
            "conversation_id",
            "user_id",
            "timestamp",
            "turn_outcome",
            "scope_decision",
            "intent",
            "context_turn_count",
            "message_length",
            "message_language",
            "message",
            "query_outcome",
            "query_duration_ms",
            "connection_acquisition_ms",
            "result_row_count",
            "result_truncated",
            "firewall_verdict",
            "firewall_reason_code",
            "model_call_count",
            "prompt_tokens",
            "completion_tokens",
            "prompt_version",
            "error_category",
            "exception_type",
            "stack_trace",
            "query_executed",
            "total_duration_ms",
            "service",
            "service_version",
            "environment",
            "lambda_request_id",
            "cold_start",
            "truncated_fields",
        }
    )
    | STAGE_FIELDS
)

# R15 environment -> R14.26 log identity vocabulary.
ENVIRONMENT_LOG_VALUE: dict[str, str] = {"local": "local", "ci": "dev", "aws": "prod"}
