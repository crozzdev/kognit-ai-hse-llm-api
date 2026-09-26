"""Model-provider abstraction: protocol, request/response types and shared policy.

``ModelProvider`` is the single provider-independent interface for
structured-output completions (R11.2, R11.12-R11.13). ``ProviderBase`` holds the
retry, repair, credential-refresh, token-ceiling and finish-reason policy
(R11.6, R11.16-R11.22, R11.26, R11.28-R11.29) so all three implementations share
one policy; only the transport differs (D5). A concrete provider implements
``_transport`` and ``_refresh_credential``; ``ProviderBase.complete`` wraps them
with the shared policy.

Import boundary B2: only ``providers/**`` may import a model-provider SDK, and
the SDK import lives in the concrete transport modules, never here.
"""

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

__all__ = [
    "AuthProviderError",
    "CompletionRequest",
    "CompletionResult",
    "Message",
    "ModelProvider",
    "ProviderBase",
    "ProviderOutputError",
    "RawCompletion",
    "RetryableProviderError",
]

CallType = Literal["scope", "intent", "sql", "answer"]
FinishReason = Literal["COMPLETED", "MAX_OUTPUT_TOKENS", "CONTENT_FILTERED", "ERROR"]

# Retry schedule (R11.6): base waits before retry 1 and retry 2, plus jitter.
_RETRY_BASE_DELAYS_MS = (500, 1000)
_RETRY_JITTER_MS = 250


class Message(BaseModel):
    """One conversation message. User text never enters the system instruction."""

    role: Literal["user", "assistant"]
    content: str


class CompletionRequest[T: BaseModel](BaseModel):
    """A structured-output completion request (R11.12)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    call_type: CallType
    system_instruction: str
    messages: tuple[Message, ...]
    output_model: type[T]
    temperature: float
    max_output_tokens: int
    timeout_ms: int
    request_id: str


class CompletionResult[T: BaseModel](BaseModel):
    """A validated structured-output completion response (R11.13, R11.15)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    output: T
    prompt_tokens: int
    completion_tokens: int
    finish_reason: FinishReason
    provider_request_id: str = ""


@dataclass(frozen=True, slots=True)
class RawCompletion:
    """The raw transport result before output parsing/validation.

    ``text`` is the model's raw structured-output text (JSON) to be parsed into
    the target model; it is empty for a non-COMPLETED finish reason.
    """

    text: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: FinishReason
    provider_request_id: str = ""


class ProviderError(Exception):
    """Base transport error, classified as retryable or not (R11.18-R11.19)."""

    retryable: bool = False


class RetryableProviderError(ProviderError):
    """Connection/transport/timeout/rate-limit/5xx failure (R11.18)."""

    retryable = True


class AuthProviderError(ProviderError):
    """Authentication failure; triggers one credential refresh (R11.26)."""


class ProviderOutputError(ProviderError):
    """Raised when a completion cannot be turned into a validated output.

    Carries the finish reason so the orchestrator maps ``CONTENT_FILTERED`` to a
    rejection (R11.20) and other reasons to ``INTENT_UNRESOLVED`` / retry-exhausted
    failures (R11.17, R11.22).
    """

    def __init__(self, finish_reason: FinishReason) -> None:
        super().__init__(f"provider completion failed: {finish_reason}")
        self.finish_reason = finish_reason


class ModelProvider(Protocol):
    """The provider-independent completion interface (R11.2)."""

    provider_id: str

    def complete[T: BaseModel](
        self, request: CompletionRequest[T]
    ) -> CompletionResult[T]: ...


class ProviderBase(ABC):
    """Shared retry / repair / refresh / finish-reason policy for all providers."""

    provider_id: str = "base"

    def __init__(self, *, max_retries: int) -> None:
        self._max_retries = max_retries

    # ── Transport seam implemented per provider ──────────────────────────────

    @abstractmethod
    def _transport(self, request: "CompletionRequest[BaseModel]") -> RawCompletion:
        """Perform one provider call and return its raw result."""

    def _refresh_credential(self) -> None:
        """Discard and re-resolve the provider credential (R11.26).

        The default is a no-op; a transport that caches a credential overrides
        this to clear its cache so the next call re-resolves.
        """
        return None

    # ── Shared policy ────────────────────────────────────────────────────────

    def complete[T: BaseModel](
        self, request: CompletionRequest[T]
    ) -> CompletionResult[T]:
        """Run one completion under the shared policy, returning a validated result.

        Applies retryable-error backoff (R11.6), one auth-driven credential
        refresh (R11.26), one reissue on ``MAX_OUTPUT_TOKENS`` (R11.21-R11.22),
        one repair on a parse failure (R11.16-R11.17), and passes through the
        ``CONTENT_FILTERED`` finish reason for the caller to map (R11.20).
        """
        raw = self._call_with_recovery(request)

        if raw.finish_reason == "MAX_OUTPUT_TOKENS":
            raw = self._call_with_recovery(request)
            if raw.finish_reason == "MAX_OUTPUT_TOKENS":
                raise ProviderOutputError("MAX_OUTPUT_TOKENS")

        if raw.finish_reason in ("CONTENT_FILTERED", "ERROR"):
            # No parse; caller maps CONTENT_FILTERED to a rejection (R11.20).
            raise ProviderOutputError(raw.finish_reason)

        parsed = self._parse(request, raw)
        if parsed is not None:
            return parsed

        # One repair attempt on a parse failure (R11.16).
        repaired = self._call_with_recovery(request)
        parsed = self._parse(request, repaired)
        if parsed is not None:
            return parsed
        # Repair budget exhausted (R11.17).
        raise ProviderOutputError(repaired.finish_reason)

    def _call_with_recovery(
        self, request: "CompletionRequest[BaseModel]"
    ) -> RawCompletion:
        """One transport call with retry backoff and a single credential refresh."""
        refreshed = False
        attempt = 0
        while True:
            try:
                return self._transport(request)
            except AuthProviderError:
                if refreshed:
                    raise
                refreshed = True
                self._refresh_credential()
            except RetryableProviderError:
                if attempt >= self._max_retries:
                    raise
                self._sleep_before_retry(attempt)
                attempt += 1

    def _sleep_before_retry(self, attempt: int) -> None:
        base = _RETRY_BASE_DELAYS_MS[min(attempt, len(_RETRY_BASE_DELAYS_MS) - 1)]
        jitter = random.uniform(0, _RETRY_JITTER_MS)
        time.sleep((base + jitter) / 1000)

    def _parse[T: BaseModel](
        self, request: CompletionRequest[T], raw: RawCompletion
    ) -> CompletionResult[T] | None:
        try:
            output = request.output_model.model_validate_json(raw.text)
        except ValidationError:
            return None
        return CompletionResult(
            output=output,
            prompt_tokens=raw.prompt_tokens,
            completion_tokens=raw.completion_tokens,
            finish_reason=raw.finish_reason,
            provider_request_id=raw.provider_request_id,
        )


