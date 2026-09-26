"""Secret resolution with env-first precedence (R15.21-R15.24, R13.29-R13.30).

``SecretResolver`` resolves each secret value with the precedence: a direct
environment variable first (zero AWS calls, R15.21), then AWS SSM Parameter Store
using the configured ``*_PARAM`` name, then AWS Secrets Manager (R15.22). A full
miss records a failed dependency status without crashing the process (R15.24).

Resolved values are cached for the lifetime of the execution environment
(R15.23) and published to the redactor as an opaque set so no secret value is
ever emitted (R13.30, R14.32). The combined resolution of all warehouse secrets
is bounded to at most two store requests and 1000 ms (R16.23).

Import boundary B3: this module and ``data/**`` are the only modules permitted to
import ``boto3``. The import is performed lazily inside the store calls so that
importing this module performs no network or credential access (R15.17).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kognit_llm.config.settings import Settings

__all__ = ["DbCredentials", "SecretResolver"]

# Combined-resolution budget for the warehouse secrets (R16.23).
_MAX_STORE_REQUESTS = 2
_RESOLUTION_BUDGET_MS = 1000


@dataclass(frozen=True, slots=True)
class DbCredentials:
    """Resolved warehouse connection identity (replaces the old DB_* globals).

    ``user`` and ``password`` are secret; ``host`` and ``port`` are classified as
    secret connection settings per R13.29. ``complete`` is false when any required
    part could not be resolved, which the health composition reports as a failed
    warehouse dependency without disclosing which value was absent.
    """

    host: str | None
    port: int
    dbname: str | None
    user: str | None
    password: str | None
    sslmode: str
    connect_timeout_ms: int

    @property
    def complete(self) -> bool:
        """True when every part needed to open a connection is present."""
        return all(
            part is not None
            for part in (self.host, self.dbname, self.user, self.password)
        )


@dataclass
class SecretResolver:
    """Env-first secret resolver with a bounded, cached AWS fallback.

    ``publish`` receives every resolved secret value as it is discovered so a
    redactor can hold them as an opaque set. ``store_requests`` counts the AWS
    store calls made, enforcing the R16.23 request budget.
    """

    settings: "Settings"
    publish: Callable[[str], None] | None = None
    _cache: dict[str, str | None] = field(default_factory=dict, init=False)
    _store_requests: int = field(default=0, init=False)
    _budget_started_ms: float | None = field(default=None, init=False)

    def database(self) -> DbCredentials:
        """Resolve the warehouse credentials, within the combined store budget."""
        self._reset_budget()
        user = self._resolve(
            env_value=self.settings.db_user,
            param_name=self.settings.db_user_param,
        )
        password = self._resolve(
            env_value=self.settings.db_password,
            param_name=self.settings.db_password_param,
        )
        return DbCredentials(
            host=self.settings.db_host,
            port=self.settings.db_port,
            dbname=self.settings.db_name,
            user=user,
            password=password,
            sslmode=self.settings.db_sslmode,
            connect_timeout_ms=self.settings.db_connect_timeout_ms,
        )

    def model_credential(self) -> str | None:
        """Resolve the model-provider credential, or None when unavailable."""
        self._reset_budget()
        return self._resolve(
            env_value=self.settings.model_api_key,
            param_name=self.settings.model_credential_param,
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    def _reset_budget(self) -> None:
        self._store_requests = 0
        self._budget_started_ms = None

    def _resolve(self, *, env_value: str | None, param_name: str | None) -> str | None:
        """Return a secret value using env-first, then SSM, then Secrets Manager."""
        if env_value is not None and env_value != "":
            self._publish(env_value)
            return env_value

        if param_name is None or param_name == "":
            return None

        cache_key = param_name
        if cache_key in self._cache:
            return self._cache[cache_key]

        value = self._resolve_from_stores(param_name)
        self._cache[cache_key] = value
        if value is not None:
            self._publish(value)
        return value

    def _resolve_from_stores(self, param_name: str) -> str | None:
        """Try SSM then Secrets Manager, honouring the request/time budget."""
        value = self._from_ssm(param_name)
        if value is not None:
            return value
        return self._from_secrets_manager(param_name)

    def _budget_exhausted(self) -> bool:
        if self._store_requests >= _MAX_STORE_REQUESTS:
            return True
        if self._budget_started_ms is None:
            self._budget_started_ms = time.monotonic() * 1000
            return False
        elapsed = time.monotonic() * 1000 - self._budget_started_ms
        return elapsed > _RESOLUTION_BUDGET_MS

    def _from_ssm(self, param_name: str) -> str | None:
        if self._budget_exhausted():
            return None
        self._store_requests += 1
        try:
            import boto3

            client = boto3.client("ssm", region_name=self.settings.aws_region)
            response = client.get_parameter(Name=param_name, WithDecryption=True)
            return response["Parameter"]["Value"]
        except Exception:
            # A store miss or transport error is not fatal (R15.24); the caller
            # records a failed dependency status. No detail is surfaced.
            return None

    def _from_secrets_manager(self, param_name: str) -> str | None:
        if self._budget_exhausted():
            return None
        self._store_requests += 1
        try:
            import boto3

            client = boto3.client(
                "secretsmanager", region_name=self.settings.aws_region
            )
            response = client.get_secret_value(SecretId=param_name)
            return response.get("SecretString")
        except Exception:
            return None

    def _publish(self, value: str) -> None:
        if self.publish is not None and value:
            self.publish(value)
