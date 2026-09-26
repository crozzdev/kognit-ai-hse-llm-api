"""Cross-field configuration validation (R16.19, R10.27-R10.28, R13.33, R14.36).

``validate_cross_field`` enforces the timeout-ordering relations and the
deployed-environment relations that no single-field bound can express. Every
violated relation is collected into one aggregated report that names the
offending configuration keys and never echoes a secret value (R15.18). The
report is raised as a ``ValueError`` so pydantic surfaces it as a single
``ValidationError`` at construction time.

Environment-vocabulary note: the R15 configuration variable uses
``local`` / ``ci`` / ``aws``. The production-only rules of R11.31, R13.33 and
R14.36 are evaluated against ``environment == "aws"``, which is the deployed
case.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kognit_llm.config.settings import Settings

__all__ = ["CrossFieldError", "validate_cross_field"]

# API Gateway integration timeout and the response-emission margin reserved
# below it, both in milliseconds (R16.19).
_API_GATEWAY_TIMEOUT_MS = 29000
_RESPONSE_MARGIN_MS = 2000


class CrossFieldError(ValueError):
    """Raised when one or more cross-field relations are violated."""


def validate_cross_field(settings: "Settings") -> "Settings":
    """Return ``settings`` unchanged, or raise with every violated relation.

    Each failing relation contributes one human-readable line naming the
    relation and the configuration keys involved. Secret values are never
    included: only key names and non-secret numeric bounds appear.
    """
    violations: list[str] = []

    if not settings.db_statement_timeout_ms < settings.turn_timeout_ms:
        violations.append(
            "db_statement_timeout_ms must be strictly less than turn_timeout_ms "
            f"({settings.db_statement_timeout_ms} >= {settings.turn_timeout_ms})"
        )

    if not settings.model_timeout_ms < settings.turn_timeout_ms:
        violations.append(
            "model_timeout_ms must be strictly less than turn_timeout_ms "
            f"({settings.model_timeout_ms} >= {settings.turn_timeout_ms})"
        )

    connect_plus_statement = (
        settings.db_connect_timeout_ms + settings.db_statement_timeout_ms
    )
    if connect_plus_statement > settings.turn_timeout_ms:
        violations.append(
            "db_connect_timeout_ms + db_statement_timeout_ms must not exceed "
            f"turn_timeout_ms ({connect_plus_statement} > {settings.turn_timeout_ms})"
        )

    if settings.turn_timeout_ms + _RESPONSE_MARGIN_MS > _API_GATEWAY_TIMEOUT_MS:
        violations.append(
            "turn_timeout_ms plus the "
            f"{_RESPONSE_MARGIN_MS} ms response margin must not exceed the "
            f"{_API_GATEWAY_TIMEOUT_MS} ms API Gateway integration timeout "
            f"(turn_timeout_ms={settings.turn_timeout_ms})"
        )

    if settings.environment == "aws" and settings.log_level == "DEBUG":
        violations.append(
            "log_level must not be DEBUG when environment is aws "
            "(keys: environment, log_level)"
        )

    if settings.environment == "aws" and settings.model_provider == "stub":
        violations.append(
            "model_provider must not be stub when environment is aws "
            "(keys: environment, model_provider)"
        )

    if settings.environment == "aws" and "*" in settings.cors_origins:
        violations.append(
            "cors_origins must not contain the wildcard '*' when environment is aws "
            "(keys: environment, cors_origins)"
        )

    if settings.db_pool_min > settings.db_pool_max:
        violations.append(
            "db_pool_min must not exceed db_pool_max "
            f"({settings.db_pool_min} > {settings.db_pool_max})"
        )

    if violations:
        raise CrossFieldError(
            "cross-field configuration validation failed: " + "; ".join(violations)
        )
    return settings
