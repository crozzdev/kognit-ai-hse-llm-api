"""AWS Bedrock provider transport (R11.1-R11.2, R11.23-R11.24, B2).

Only this module (and ``openai_compatible.py``) imports the Bedrock SDK, and the
import is lazy so selecting a different provider pulls in no SDK (R15.17, B2). The
retry, repair, credential-refresh, token-ceiling and finish-reason policy is
inherited from ``ProviderBase``; this module supplies only the transport, using
the Bedrock Converse API for structured JSON output.
"""

import json
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

__all__ = ["BedrockProvider"]

_STOP_REASON_MAP = {
    "end_turn": "COMPLETED",
    "stop_sequence": "COMPLETED",
    "max_tokens": "MAX_OUTPUT_TOKENS",
    "content_filtered": "CONTENT_FILTERED",
    "guardrail_intervened": "CONTENT_FILTERED",
}


class BedrockProvider(ProviderBase):
    """Structured-output completions over the AWS Bedrock Converse API."""

    provider_id = "bedrock"

    def __init__(
        self, *, settings: "Settings", secrets: "SecretResolver"
    ) -> None:
        super().__init__(max_retries=settings.model_max_retries)
        self._settings = settings
        self._secrets = secrets
        self._client: Any | None = None

    def _client_or_build(self) -> Any:
        if self._client is None:
            import boto3

            # Explicit credentials (e.g. a cross-account key from SSM) take
            # precedence; otherwise boto3's default chain (Lambda role / local
            # profile) is used. Both keys must be present to switch.
            access_key = self._settings.bedrock_access_key_id
            secret_key = self._settings.bedrock_secret_access_key
            if access_key and secret_key:
                self._client = boto3.client(
                    "bedrock-runtime",
                    region_name=self._settings.aws_region,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                )
            else:
                self._client = boto3.client(
                    "bedrock-runtime", region_name=self._settings.aws_region
                )
        return self._client

    def _refresh_credential(self) -> None:
        self._client = None

    def _transport(
        self, request: "CompletionRequest[BaseModel]"
    ) -> RawCompletion:
        client = self._client_or_build()
        messages = [
            {"role": m.role, "content": [{"text": m.content}]}
            for m in request.messages
        ]
        try:
            response = client.converse(  # type: ignore[attr-defined]
                modelId=self._settings.model_id,
                system=[{"text": request.system_instruction}],
                messages=messages,
                inferenceConfig={
                    "temperature": request.temperature,
                    "maxTokens": request.max_output_tokens,
                },
            )
        except Exception as err:  # noqa: BLE001 - classified below
            raise self._classify(err) from None

        result = cast(dict[str, Any], response)
        stop_reason = str(result.get("stopReason", ""))
        finish = cast(FinishReason, _STOP_REASON_MAP.get(stop_reason, "ERROR"))
        text = _extract_text(result)
        usage = result.get("usage", {})
        metadata = result.get("ResponseMetadata", {})
        return RawCompletion(
            text=text,
            prompt_tokens=int(usage.get("inputTokens", 0)),
            completion_tokens=int(usage.get("outputTokens", 0)),
            finish_reason=finish,
            provider_request_id=str(metadata.get("RequestId", "")),
        )

    def _classify(self, err: Exception) -> Exception:
        name = type(err).__name__.lower()
        if "accessdenied" in name or "unrecognizedclient" in name or "auth" in name:
            return AuthProviderError(str(err))
        return RetryableProviderError(str(err))


def _extract_text(response: dict[str, Any]) -> str:
    """Concatenate the text blocks of a Converse response, or a JSON fallback."""
    output = response.get("output")
    if isinstance(output, dict):
        message = output.get("message")
        if isinstance(message, dict):
            blocks = message.get("content")
            if isinstance(blocks, list):
                return "".join(
                    str(block.get("text", ""))
                    for block in blocks
                    if isinstance(block, dict)
                )
    return json.dumps(response)
