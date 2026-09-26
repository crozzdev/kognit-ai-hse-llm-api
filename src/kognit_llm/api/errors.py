"""Exception hierarchy and exception-to-HTTP mapping (§Error Handling, R1, R13).

Every ``LlmApiError`` carries an ``ErrorCategory``, an HTTP status and a
``TurnOutcome``, plus a fixed, category-level user message. No exception carries
SQL text, schema identifiers, host names, role names or credential values
(R13.9, R7.34). A failed chat request serializes to exactly
``{error_category, message, request_id}`` so two failures of one category differ
only in ``request_id`` (R13.32).

``ClarificationNeeded`` deliberately omits ``error_category`` from the body
(R14.10); its ``category`` attribute is ``None``.
"""

from kognit_llm.agent.state import ErrorCategory, TurnOutcome
from kognit_llm.api.models import ErrorBody

__all__ = [
    "ClarificationNeeded",
    "ConfigurationError",
    "FirewallRejected",
    "GraphInvariantViolation",
    "IntentUnresolved",
    "LlmApiError",
    "ProviderError",
    "RequestValidationError",
    "ScopeRejected",
    "TurnTimeout",
    "WarehouseError",
    "error_body",
]


class LlmApiError(Exception):
    """Base error carrying category, HTTP status, outcome and a fixed message.

    Subclasses set the class attributes; the fixed ``user_message`` is the only
    text placed in a response body for that category.
    """

    category: ErrorCategory | None = ErrorCategory.INTERNAL_ERROR
    http_status: int = 500
    outcome: TurnOutcome = TurnOutcome.INTERNAL_ERROR
    user_message: str = "The request could not be completed."


# ── Request-time errors (graph not necessarily entered) ──────────────────────


class ConfigurationError(LlmApiError):
    """Chat-critical configuration missing or invalid (R15.19, R11.31)."""

    category = ErrorCategory.INTERNAL_ERROR
    http_status = 503
    outcome = TurnOutcome.INTERNAL_ERROR
    user_message = "The assistant is temporarily unavailable."


class RequestValidationError(LlmApiError):
    """Request body/headers failed validation (R1.3-R1.5, R1.20-R1.22, R13.34)."""

    category = ErrorCategory.VALIDATION_ERROR
    http_status = 422
    outcome = TurnOutcome.INTERNAL_ERROR
    user_message = "The request was not valid."


# ── In-turn terminal outcomes (HTTP 200) ─────────────────────────────────────


class ScopeRejected(LlmApiError):
    """Scope guard produced OUT_OF_SCOPE or UNSAFE (R2.11-R2.12)."""

    category = ErrorCategory.SCOPE_REJECTED
    http_status = 200
    outcome = TurnOutcome.SCOPE_REJECTED
    user_message = (
        "I can only answer approved Health and Safety analytics questions."
    )


class ClarificationNeeded(LlmApiError):
    """Intent classifier needs clarification; no error_category in the body."""

    category = None
    http_status = 200
    outcome = TurnOutcome.CLARIFICATION_REQUESTED
    user_message = "Could you clarify the question?"


class IntentUnresolved(LlmApiError):
    """Analytics intent failed validation / repair exhausted (R3.7, R11.17)."""

    category = ErrorCategory.INTENT_UNRESOLVED
    http_status = 200
    outcome = TurnOutcome.INTENT_UNRESOLVED
    user_message = "I could not interpret that question."


class FirewallRejected(LlmApiError):
    """Firewall rejected the generated SQL twice (R5.8, R6.17)."""

    category = ErrorCategory.FIREWALL_REJECTED
    http_status = 200
    outcome = TurnOutcome.FIREWALL_REJECTED
    user_message = "I could not answer that question safely."


# ── Provider errors ──────────────────────────────────────────────────────────


class ProviderError(LlmApiError):
    """Model-provider failure (R11.7, R11.17, R11.20-R11.22, R11.29)."""

    category = ErrorCategory.PROVIDER_ERROR
    http_status = 200
    outcome = TurnOutcome.PROVIDER_ERROR
    user_message = "I could not answer that question."


class ProviderUnavailable(ProviderError):
    """Retries exhausted or credential refresh failed (R11.7, R11.26)."""

    http_status = 503
    user_message = "The assistant is temporarily unavailable."


class ProviderOutputInvalid(ProviderError):
    """Repair budget exhausted (R11.17)."""

    outcome = TurnOutcome.INTENT_UNRESOLVED


class ProviderContentFiltered(ProviderError):
    """Provider returned CONTENT_FILTERED; respond intent=REJECTED (R11.20)."""

    user_message = "I cannot answer that request."


class TokenCeilingExceeded(ProviderError):
    """Per-turn token ceiling reached (R11.29, R16.30)."""


# ── Warehouse errors ─────────────────────────────────────────────────────────


class WarehouseError(LlmApiError):
    """Warehouse failure (R7.19, R7.21, R7.27-R7.30)."""

    category = ErrorCategory.WAREHOUSE_ERROR
    http_status = 200
    outcome = TurnOutcome.WAREHOUSE_ERROR
    user_message = "The requested HSE data is unavailable."


class WarehouseUnavailable(WarehouseError):
    """Connect, TLS, pool-acquisition or auth failure (R7.21, R7.27-R7.28)."""

    http_status = 503
    user_message = "HSE data is temporarily unavailable."


class WarehouseStatementTimeout(WarehouseError):
    """Statement timeout at the warehouse (R7.6); TIMEOUT category."""

    category = ErrorCategory.TIMEOUT
    outcome = TurnOutcome.WAREHOUSE_TIMEOUT
    user_message = "The question took too long to answer."


class WarehousePrivilegeDenied(WarehouseError):
    """Insufficient privilege on a referenced object; object withheld (R7.29)."""


class WarehouseUndefinedObject(WarehouseError):
    """Referenced table or column undefined; identifier withheld (R7.30)."""


class WarehouseWriteRejected(WarehouseError):
    """Read-only violation surfaced by the warehouse (R7.19)."""


# ── Orchestration errors ─────────────────────────────────────────────────────


class TurnTimeout(LlmApiError):
    """The configured turn timeout elapsed (R10.11)."""

    category = ErrorCategory.TIMEOUT
    http_status = 504
    outcome = TurnOutcome.TURN_TIMEOUT
    user_message = "The request timed out."


class GraphInvariantViolation(LlmApiError):
    """State-guard violation or unhandled exception (R10.20-R10.21, R10.32)."""

    category = ErrorCategory.INTERNAL_ERROR
    http_status = 200
    outcome = TurnOutcome.INTERNAL_ERROR
    user_message = "The request could not be completed."


def error_body(error: LlmApiError, request_id: str) -> ErrorBody:
    """Build the uniform failure body for ``error`` (R13.32).

    The ``error_category`` is the category name, or the literal ``NONE`` when the
    error omits a category (only ``ClarificationNeeded`` does), so the field is
    always a string. Callers that must omit the field entirely (clarification)
    use the response model rather than this helper.
    """
    category = error.category.value if error.category is not None else "NONE"
    return ErrorBody(
        error_category=category,
        message=error.user_message,
        request_id=request_id,
    )
