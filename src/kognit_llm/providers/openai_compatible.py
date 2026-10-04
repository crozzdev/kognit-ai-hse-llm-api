"""OpenAI-compatible provider transport (R11.1-R11.2, R11.23-R11.24, B2).

Only this module (and ``bedrock.py``) imports the OpenAI-compatible SDK, and the
import is lazy so selecting a different provider pulls in no SDK (R15.17, B2). The
retry, repair, credential-refresh, token-ceiling and finish-reason policy is
inherited from ``ProviderBase``; this module supplies only the transport.
"""

from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from kognit_llm.providers.base import (
    AuthProviderError,
    CompletionRequest,
    FinishReason,
    ProviderBase,
    RawCompletion,
    RetryableProviderError,
)

if TYPE_CHECKING:
    from kognit_llm.config.secrets import SecretResolver
    from kognit_llm.config.settings import Settings

__all__ = ["OpenAICompatibleProvider"]

_FINISH_REASON_MAP = {
    "stop": "COMPLETED",
    "length": "MAX_OUTPUT_TOKENS",
    "content_filter": "CONTENT_FILTERED",
}


class OpenAICompatibleProvider(ProviderBase):
    """Structured-output completions over an OpenAI-compatible chat API."""

    provider_id = "openai_compatible"

    def __init__(
        self, *, settings: "Settings", secrets: "SecretResolver"
    ) -> None:
        super().__init__(max_retries=settings.model_max_retries)
        self._settings = settings
        self._secrets = secrets
        self._credential: str | None = None
        self._client: Any | None = None

    def _client_or_build(self) -> Any:
        if self._client is None:
            self._credential = self._secrets.model_credential()
            self._client = self._build_client(self._credential)
        return self._client

    def _build_client(self, credential: str | None) -> Any:
        try:
            from openai import OpenAI  # ty: ignore[unresolved-import]
        except ImportError as err:  # pragma: no cover - depends on optional SDK
            raise RuntimeError(
                "the openai SDK is required for the openai_compatible provider"
            ) from err
        return OpenAI(
            api_key=credential or "",
            base_url=self._settings.model_endpoint or None,
        )

    def _refresh_credential(self) -> None:
        self._client = None
        self._credential = None

    def _transport(
        self, request: "CompletionRequest[BaseModel]"
    ) -> RawCompletion:
        client = self._client_or_build()
        messages: list[dict[str, str]] = [
            {"role": "system", "content": request.system_instruction}
        ]
        messages.extend(
            {"role": m.role, "content": m.content} for m in request.messages
        )
        try:
            response = client.chat.completions.create(
                model=self._settings.model_id,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_output_tokens,
                timeout=request.timeout_ms / 1000,
                response_format={"type": "json_object"},
            )
        except Exception as err:  # noqa: BLE001 - classified below
            raise self._classify(err) from None

        choice = response.choices[0]
        usage = response.usage
        finish = cast(
            FinishReason, _FINISH_REASON_MAP.get(choice.finish_reason or "", "ERROR")
        )
        return RawCompletion(
            text=choice.message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            finish_reason=finish,
            provider_request_id=getattr(response, "id", "") or "",
        )

    def _classify(self, err: Exception) -> Exception:
        name = type(err).__name__.lower()
        if "auth" in name or "permission" in name:
            return AuthProviderError(str(err))
        if any(
            token in name
            for token in ("timeout", "connection", "ratelimit", "apierror", "internal")
        ):
            return RetryableProviderError(str(err))
        return RetryableProviderError(str(err))
