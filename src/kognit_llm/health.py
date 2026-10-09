"""Health composition for ``GET /health`` (R1.19, R7.10, R15.24, R15.31).

``compose_health`` gathers the four dependency statuses -- configuration,
warehouse, model-provider configuration and approved-schema verification -- into
one report. It never raises and never echoes a connection detail or secret
value: an unresolved dependency is reported as ``failed`` with a key name only,
so the route can always answer HTTP 200 (R15.24, R15.31).

The warehouse and schema-verification probes belong to later milestones
(``data/probes.py``, ``schema/context_provider.py``); until they are wired,
``compose_health`` accepts them as optional callables and reports ``unknown``
when a probe is absent, so the foundation stays runnable end to end.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from kognit_llm.config.secrets import SecretResolver
    from kognit_llm.config.settings import Settings

__all__ = ["DependencyStatus", "HealthReport", "compose_health"]

StatusValue = Literal["ok", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    """One dependency's health, carrying no connection detail or secret value."""

    name: str
    status: StatusValue
    detail: str = ""


@dataclass(frozen=True, slots=True)
class HealthReport:
    """The composed health of every dependency (R1.19)."""

    configuration: DependencyStatus
    warehouse: DependencyStatus
    model_provider: DependencyStatus
    schema_verification: DependencyStatus

    @property
    def overall(self) -> StatusValue:
        """``ok`` only when no dependency is ``failed``."""
        statuses = (
            self.configuration.status,
            self.warehouse.status,
            self.model_provider.status,
            self.schema_verification.status,
        )
        return "failed" if "failed" in statuses else "ok"


def _configuration_status(settings: "Settings | None") -> DependencyStatus:
    if settings is None:
        return DependencyStatus(
            "configuration", "failed", "configuration failed validation"
        )
    return DependencyStatus("configuration", "ok")


def _model_provider_status(settings: "Settings | None") -> DependencyStatus:
    """Report model-provider *configuration* availability (R1.19), not liveness."""
    if settings is None:
        return DependencyStatus("model_provider", "failed", "configuration unavailable")
    if settings.model_provider == "stub":
        # A stub in the deployed environment is a configuration failure
        # (R11.31); cross-field validation already blocks aws+stub, so reaching
        # here means a non-deployed environment where stub is acceptable.
        return DependencyStatus("model_provider", "ok", "stub provider")
    if settings.model_id is None or settings.model_id == "":
        return DependencyStatus(
            "model_provider", "failed", "model_id is not configured"
        )
    return DependencyStatus("model_provider", "ok")


def _warehouse_status(
    settings: "Settings | None",
    resolver: "SecretResolver | None",
    probe: Callable[[], DependencyStatus] | None,
) -> DependencyStatus:
    if probe is not None:
        try:
            return probe()
        except Exception:
            # A probe must never crash health composition (R7.10, R15.24).
            return DependencyStatus("warehouse", "failed", "warehouse probe failed")
    if settings is None or resolver is None:
        return DependencyStatus("warehouse", "unknown", "warehouse probe not wired")
    # Without a live probe, report credential resolvability only, naming the
    # absent key rather than any value (R7.10).
    creds = resolver.database()
    if not creds.complete:
        return DependencyStatus(
            "warehouse", "failed", "warehouse credentials or host not resolved"
        )
    return DependencyStatus("warehouse", "unknown", "warehouse probe not wired")


def compose_health(
    settings: "Settings | None",
    resolver: "SecretResolver | None" = None,
    *,
    warehouse_probe: Callable[[], DependencyStatus] | None = None,
    schema_probe: Callable[[], DependencyStatus] | None = None,
) -> HealthReport:
    """Compose the four dependency statuses without raising (R1.19, R15.31).

    ``settings`` is ``None`` when configuration validation failed; every other
    dependency is then reported ``failed`` or ``unknown`` and the route still
    answers HTTP 200 (R15.19).
    """
    schema_status: DependencyStatus
    if schema_probe is not None:
        try:
            schema_status = schema_probe()
        except Exception:
            schema_status = DependencyStatus(
                "schema_verification", "failed", "schema verification failed"
            )
    else:
        schema_status = DependencyStatus(
            "schema_verification", "unknown", "schema verification not wired"
        )

    return HealthReport(
        configuration=_configuration_status(settings),
        warehouse=_warehouse_status(settings, resolver, warehouse_probe),
        model_provider=_model_provider_status(settings),
        schema_verification=schema_status,
    )
