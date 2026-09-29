"""Unit tests for the Bedrock provider transport (R11.1-R11.2, R11.23-R11.24, B2).

The AWS SDK is never reached: ``boto3.client`` is monkeypatched with a fake
Bedrock-runtime client, so these tests verify lazy client construction, the
credential-refresh reset, the Converse stop-reason mapping, response text
extraction and error classification without any network I/O (conftest blocks
sockets).
"""

from typing import Any

import pytest
from pydantic import BaseModel

from kognit_llm.config.secrets import SecretResolver
from kognit_llm.config.settings import settings_from_mapping
from kognit_llm.providers.base import (
    AuthProviderError,
    CompletionRequest,
    Message,
    RetryableProviderError,
)
from kognit_llm.providers.bedrock import BedrockProvider


class Verdict(BaseModel):
    decision: str


class FakeBedrockClient:
    """Records ``converse`` calls and returns a scripted response or raises."""

    def __init__(
        self, response: dict[str, Any] | None, error: Exception | None
    ) -> None:
        self._response = response
        self._error = error
        self.converse_calls = 0
        self.last_kwargs: dict[str, Any] = {}

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.converse_calls += 1
        self.last_kwargs = kwargs
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _converse_response(text: str, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "output": {"message": {"content": [{"text": text}]}},
        "stopReason": stop_reason,
        "usage": {"inputTokens": 11, "outputTokens": 7},
        "ResponseMetadata": {"RequestId": "aws-req-1"},
    }


def _make_provider() -> BedrockProvider:
    settings = settings_from_mapping(
        {
            "model_provider": "bedrock",
            "model_id": "amazon.nova-pro-v1:0",
            "aws_region": "us-east-1",
        }
    )
    secrets = SecretResolver(settings=settings)
    return BedrockProvider(settings=settings, secrets=secrets)


def _request() -> CompletionRequest[Verdict]:
    return CompletionRequest[Verdict](
        call_type="scope",
        system_instruction="Classify.",
        messages=(Message(role="user", content="hello"),),
        output_model=Verdict,
        temperature=0.0,
        max_output_tokens=64,
        timeout_ms=5000,
        request_id="req-1",
    )


def _patch_boto3(
    monkeypatch: pytest.MonkeyPatch, client: FakeBedrockClient
) -> list[str]:
    """Patch ``boto3.client`` to return ``client`` and record requested services."""
    import boto3

    requested: list[str] = []

    def fake_client(service: str, **_kwargs: Any) -> FakeBedrockClient:
        requested.append(service)
        return client

    monkeypatch.setattr(boto3, "client", fake_client)
    return requested


def test_transport_builds_client_lazily_and_maps_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeBedrockClient(_converse_response('{"decision":"IN_SCOPE"}'), None)
    requested = _patch_boto3(monkeypatch, client)

    provider = _make_provider()
    result = provider.complete(_request())

    assert requested == ["bedrock-runtime"]
    assert result.output.decision == "IN_SCOPE"
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 7
    assert result.finish_reason == "COMPLETED"
    assert result.provider_request_id == "aws-req-1"
    assert client.converse_calls == 1
    # The system instruction and message are forwarded in Converse shape.
    assert client.last_kwargs["system"] == [{"text": "Classify."}]
    assert client.last_kwargs["messages"][0]["role"] == "user"


def test_transport_client_is_cached_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeBedrockClient(_converse_response('{"decision":"IN_SCOPE"}'), None)
    requested = _patch_boto3(monkeypatch, client)

    provider = _make_provider()
    provider.complete(_request())
    provider.complete(_request())

    # boto3.client built once; the cached client served the second call.
    assert requested == ["bedrock-runtime"]


def test_refresh_credential_rebuilds_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeBedrockClient(_converse_response('{"decision":"IN_SCOPE"}'), None)
    requested = _patch_boto3(monkeypatch, client)

    provider = _make_provider()
    provider.complete(_request())
    provider._refresh_credential()
    provider.complete(_request())

    # A refresh cleared the cached client, forcing a second boto3.client build.
    assert requested == ["bedrock-runtime", "bedrock-runtime"]


@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [
        ("end_turn", "COMPLETED"),
        ("stop_sequence", "COMPLETED"),
        ("max_tokens", "MAX_OUTPUT_TOKENS"),
        ("content_filtered", "CONTENT_FILTERED"),
        ("guardrail_intervened", "CONTENT_FILTERED"),
        ("something_unknown", "ERROR"),
    ],
)
def test_stop_reason_mapping(
    monkeypatch: pytest.MonkeyPatch, stop_reason: str, expected: str
) -> None:
    text = '{"decision":"IN_SCOPE"}'
    client = FakeBedrockClient(_converse_response(text, stop_reason), None)
    _patch_boto3(monkeypatch, client)

    provider = _make_provider()
    raw = provider._transport(_request())
    assert raw.finish_reason == expected


def test_transport_extracts_concatenated_text_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "output": {
            "message": {"content": [{"text": '{"decision":'}, {"text": '"IN_SCOPE"}'}]}
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 1},
        "ResponseMetadata": {"RequestId": "r"},
    }
    client = FakeBedrockClient(response, None)
    _patch_boto3(monkeypatch, client)

    provider = _make_provider()
    raw = provider._transport(_request())
    assert raw.text == '{"decision":"IN_SCOPE"}'


class _AccessDeniedException(Exception):
    pass


class _ThrottlingException(Exception):
    pass


def test_access_denied_is_classified_as_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeBedrockClient(None, _AccessDeniedException("no access"))
    _patch_boto3(monkeypatch, client)

    provider = _make_provider()
    with pytest.raises(AuthProviderError):
        provider._transport(_request())


def test_throttling_is_classified_as_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeBedrockClient(None, _ThrottlingException("slow down"))
    _patch_boto3(monkeypatch, client)

    provider = _make_provider()
    with pytest.raises(RetryableProviderError):
        provider._transport(_request())
