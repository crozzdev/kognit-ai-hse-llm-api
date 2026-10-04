"""Application settings resolved from the ``KOGNIT_LLM_`` environment (R15).

One frozen ``Settings`` model carries one field per row of the R15 configuration
table, with the tabled types, bounds and defaults. The model is constructed once
per execution environment through ``get_settings`` (R15.7) and can also be built
from an explicit mapping through ``settings_from_mapping`` with no environment,
no AWS credentials and no network access (R15.25-R15.26).

Import-time purity (R15.17): importing this module performs no network call and
no secret-store call. Secret *values* are never read here; only the secret-store
*parameter names* are configuration. Actual secret resolution is deferred to
``config.secrets.SecretResolver``.
"""

from collections.abc import Mapping
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from kognit_llm.config.crossfield import validate_cross_field

__all__ = ["Settings", "get_settings", "settings_from_mapping"]

# Sentinel init keyword that switches Settings construction to explicit-mapping
# mode, in which no environment, dotenv or secret-store source contributes.
_ISOLATED_FLAG = "_kognit_isolated"


class Settings(BaseSettings):
    """Validated configuration for one execution environment (R15.6-R15.7).

    Field names are flat and match the R15 table exactly (minus the shared
    ``KOGNIT_LLM_`` prefix), so the environment variable names stay as tabled.
    """

    model_config = SettingsConfigDict(
        env_prefix="KOGNIT_LLM_",
        env_nested_delimiter=None,
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    # ── General ──────────────────────────────────────────────────────────────
    environment: Literal["local", "ci", "aws"] = "local"
    aws_region: str = "us-east-1"
    port: Annotated[int, Field(ge=1024, le=65535)] = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: list[str] = []
    expose_executed_sql: bool = False
    service_version: str = "0.1.0"

    # ── Message and answer shaping ───────────────────────────────────────────
    message_max_chars: Annotated[int, Field(ge=1, le=8000)] = 2000
    answer_max_chars: Annotated[int, Field(ge=1, le=2000)] = 600
    answer_language: Literal["auto", "es", "en"] = "auto"

    # ── Dates and intent ─────────────────────────────────────────────────────
    reference_timezone: str = "America/Bogota"
    first_day_of_week: Literal["MONDAY", "SUNDAY"] = "MONDAY"
    default_lookback_days: Annotated[int, Field(ge=1, le=3650)] = 365
    intent_confidence_threshold: Annotated[float, Field(ge=0.00, le=1.00)] = 0.60

    # ── Warehouse connection ─────────────────────────────────────────────────
    db_host: str | None = None
    db_port: Annotated[int, Field(ge=1, le=65535)] = 5432
    db_name: str | None = None
    db_schema: str = "public"
    db_role: str = "llm_read"
    db_sslmode: Literal["require", "verify-full", "disable"] = "require"
    db_user_param: str = "/kognit/db/LLM_READ_USER"
    db_password_param: str = "/kognit/db/LLM_READ_PASSWORD"
    db_user: str | None = None
    db_password: str | None = None
    db_connect_timeout_ms: Annotated[int, Field(ge=100, le=30000)] = 2000
    db_statement_timeout_ms: Annotated[int, Field(ge=1000, le=60000)] = 10000
    db_pool_max: Annotated[int, Field(ge=1, le=10)] = 2
    db_pool_min: Annotated[int, Field(ge=0, le=10)] = 1

    # ── Result caps ──────────────────────────────────────────────────────────
    row_cap: Annotated[int, Field(ge=1, le=10000)] = 1000
    max_result_columns: Annotated[int, Field(ge=1, le=200)] = 50
    max_result_bytes: Annotated[int, Field(ge=1024, le=16777216)] = 1048576
    max_ranking_size: Annotated[int, Field(ge=1, le=100)] = 25

    # ── Model provider ───────────────────────────────────────────────────────
    model_provider: Literal["stub", "openai_compatible", "bedrock"] = "stub"
    model_id: str | None = None
    model_endpoint: str | None = None
    model_credential_param: str | None = None
    model_api_key: str | None = None
    # Optional explicit AWS credentials for Bedrock. When set (e.g. a cross-account
    # key resolved from SSM in Lambda), the Bedrock client uses them instead of the
    # ambient role/profile; when absent, boto3's default credential chain applies.
    bedrock_access_key_id: str | None = None
    bedrock_secret_access_key: str | None = None
    model_timeout_ms: Annotated[int, Field(ge=1000, le=60000)] = 15000
    model_temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.0
    model_max_output_tokens: Annotated[int, Field(ge=256, le=8192)] = 1024
    model_max_retries: Annotated[int, Field(ge=0, le=5)] = 2
    model_calls_per_turn_max: Annotated[int, Field(ge=1, le=10)] = 4
    turn_token_ceiling: Annotated[int, Field(ge=1000, le=200000)] = 12000
    prompt_version: str = "v1"

    # ── Turn budget ──────────────────────────────────────────────────────────
    turn_timeout_ms: Annotated[int, Field(ge=1000, le=29000)] = 25000

    # ── Schema context ───────────────────────────────────────────────────────
    schema_context_token_budget: Annotated[int, Field(ge=500, le=32000)] = 4000
    include_dimension_values: bool = True
    dimension_value_max: Annotated[int, Field(ge=1, le=500)] = 50
    schema_cache_ttl_seconds: Annotated[int, Field(ge=0, le=86400)] = 3600

    # ── SQL complexity bounds ────────────────────────────────────────────────
    max_statement_chars: Annotated[int, Field(ge=100, le=20000)] = 4000
    max_join_count: Annotated[int, Field(ge=1, le=20)] = 8
    max_subquery_depth: Annotated[int, Field(ge=1, le=10)] = 3
    max_set_operation_arms: Annotated[int, Field(ge=1, le=10)] = 3
    inline_group_rows_max: Annotated[int, Field(ge=1, le=20)] = 5

    # ── Conversation store ───────────────────────────────────────────────────
    conversation_store: Literal["memory"] = "memory"
    conversation_turn_max: Annotated[int, Field(ge=1, le=100)] = 10
    conversation_max: Annotated[int, Field(ge=1, le=10000)] = 100
    conversation_ttl_seconds: Annotated[int, Field(ge=60, le=86400)] = 1800
    conversation_char_budget: Annotated[int, Field(ge=100000, le=100000000)] = 5000000

    # ── Request limits ───────────────────────────────────────────────────────
    request_body_max_bytes: Annotated[int, Field(ge=1024, le=1048576)] = 16384
    rate_limit_per_minute: Annotated[int, Field(ge=1, le=10000)] = 60
    concurrent_request_max: Annotated[int, Field(ge=1, le=100)] = 10

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order sources, and drop environment sources in isolated mode.

        When ``_kognit_isolated`` is present in the init arguments (used by
        ``settings_from_mapping``), only the explicit init values contribute, so
        construction touches no environment, dotenv file or secret file
        (R15.25-R15.26). Otherwise the normal precedence applies: explicit init
        values first, then environment, then dotenv, then file secrets.
        """
        init_data = getattr(init_settings, "init_kwargs", {})
        if init_data.get(_ISOLATED_FLAG):
            return (init_settings,)
        return (init_settings, env_settings, dotenv_settings, file_secret_settings)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept the tabled comma-separated string list form for CORS origins."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _cross_field(self) -> "Settings":
        """Enforce the timeout-ordering and environment relations (R16.19)."""
        return validate_cross_field(self)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide ``Settings``, constructed once (R15.7)."""
    return Settings()


def settings_from_mapping(values: Mapping[str, Any]) -> Settings:
    """Build ``Settings`` from an explicit mapping with no environment access.

    Field names in ``values`` are the flat ``Settings`` attribute names (without
    the ``KOGNIT_LLM_`` prefix). No environment variable, dotenv file or secret
    file contributes to the result (R15.25-R15.26); only the supplied mapping and
    the tabled defaults do.
    """
    data: dict[str, Any] = dict(values)
    data[_ISOLATED_FLAG] = True
    return Settings(**data)
