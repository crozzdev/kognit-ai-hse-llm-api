"""Health and service-identity routes (R1.18-R1.19, R15.31, R15.37).

``GET /health`` (and, for the API Gateway payloads of R15.37, ``GET /llm/health``)
returns HTTP 200 with the composed dependency statuses, including a warehouse
status and a model-provider configuration status, even with no reachable secret
store (R15.31). ``GET /`` returns the service identity
``{service, service_version, environment}``. Neither route emits a chat request
log entry (R14.37).
"""

from typing import TYPE_CHECKING

from fastapi import APIRouter

from kognit_llm.api.models import HealthBody
from kognit_llm.config.secrets import SecretResolver
from kognit_llm.health import compose_health

if TYPE_CHECKING:
    from kognit_llm.config.settings import Settings

__all__ = ["ENVIRONMENT_LOG_VALUE", "SERVICE_NAME", "build_health_router"]

SERVICE_NAME = "kognit-ai-hse-llm-api"

# Map the R15 environment vocabulary to the R14.26 log identity vocabulary.
ENVIRONMENT_LOG_VALUE = {"local": "local", "ci": "dev", "aws": "prod"}


def build_health_router(settings: "Settings") -> APIRouter:
    """Return a router carrying ``GET /``, ``GET /health`` and ``GET /llm/health``."""
    router = APIRouter()

    def _health() -> HealthBody:
        resolver = SecretResolver(settings=settings)
        report = compose_health(settings, resolver)
        return HealthBody(
            warehouse=report.warehouse.status,
            model_provider=report.model_provider.status,
            configuration=report.configuration.status,
            schema_verification=report.schema_verification.status,
            overall=report.overall,
        )

    @router.get("/", tags=["service"])
    def service_identity() -> dict[str, str]:
        return {
            "service": SERVICE_NAME,
            "service_version": settings.service_version,
            "environment": ENVIRONMENT_LOG_VALUE.get(
                settings.environment, settings.environment
            ),
        }

    @router.get("/health", tags=["health"])
    def health() -> HealthBody:
        return _health()

    # API Gateway may deliver the health payload under the /llm base path (R15.37).
    @router.get("/llm/health", include_in_schema=False, tags=["health"])
    def health_with_base_path() -> HealthBody:
        return _health()

    return router
