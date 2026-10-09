"""Unit tests for the OpenAI-compatible provider transport (R11.1-R11.2, B2).

The OpenAI SDK is optional and never installed for the tests; the provider's
``_build_client`` is patched to return a fake client, so these tests verify
credential resolution through ``SecretResolver``, lazy client construction, the
refresh reset, the finish-reason mapping and error classification without any
network I/O (conftest blocks sockets).
"""

from types import SimpleNamespace
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
from kognit_llm.providers.openai_compatible import OpenAICompatibleProvider


class Verdict(BaseModel):
    decision: str


class FakeCompletions:
    def __init__(self, response: Any, error: Exception | None) -> None:
        self._response = response
        self._error = error
        self.create_calls = 0
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.create_calls += 1
        self.last_kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._response


class FakeOpenAIClient:
    def __init__(self, response: Any, error: Exception | None) -> None:
        self.completions = FakeCompletions(response, error)
        self.chat = SimpleNamespace(completions=self.completions)


def _openai_response(text: str, finish_reason: str = "stop") -> Any:
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=13, completion_tokens=4)
    return SimpleNamespace(choices=[choice], usage=usage, id="resp-1")


def _make_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: FakeOpenAIClient,
    api_key: str | None = "sk-test",
) -> OpenAICompatibleProvider:
    settings = settings_from_mapping(
        {
            "model_provider": "openai_compatible",
            "model_id": "gpt-test",
            "model_endpoint": "https://example.invalid/v1",
            "model_api_key": api_key,
        }
    )
    secrets = SecretResolver(settings=settings)
    provider = OpenAICompatibleProvider(settings=settings, secrets=secrets)
    # Avoid importing the optional openai SDK: substitute the client builder.
    monkeypatch.setattr(provider, "_build_client", lambda _credential: client)
    return provider


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


def test_transport_maps_completed_and_forwards_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeOpenAIClient(_openai_response('{"decision":"IN_SCOPE"}'), None)
    provider = _make_provider(monkeypatch, client=client)

    result = provider.complete(_request())

    assert result.output.decision == "IN_SCOPE"
    assert result.prompt_tokens == 13
    assert result.completion_tokens == 4
    assert result.finish_reason == "COMPLETED"
    assert result.provider_request_id == "resp-1"
    # System instruction is the first message, user turn follows.
    sent = client.completions.last_kwargs["messages"]
    assert sent[0] == {"role": "system", "content": "Classify."}
    assert sent[1] == {"role": "user", "content": "hello"}


def test_credential_from_env_is_used_for_client_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The env-supplied api key is resolved once and passed to the builder."""
    client = FakeOpenAIClient(_openai_response('{"decision":"IN_SCOPE"}'), None)
    settings = settings_from_mapping(
        {
            "model_provider": "openai_compatible",
            "model_id": "gpt-test",
            "model_api_key": "sk-live",
        }
    )
    secrets = SecretResolver(settings=settings)
    provider = OpenAICompatibleProvider(settings=settings, secrets=secrets)

    seen: list[str | None] = []

    def fake_build(credential: str | None) -> FakeOpenAIClient:
        seen.append(credential)
        return client

    monkeypatch.setattr(provider, "_build_client", fake_build)
    provider.complete(_request())

    assert seen == ["sk-live"]


def test_client_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenAIClient(_openai_response('{"decision":"IN_SCOPE"}'), None)
    settings = settings_from_mapping(
        {
            "model_provider": "openai_compatible",
            "model_id": "gpt-test",
            "model_api_key": "k",
        }
    )
    secrets = SecretResolver(settings=settings)
    provider = OpenAICompatibleProvider(settings=settings, secrets=secrets)

    builds = 0

    def fake_build(_credential: str | None) -> FakeOpenAIClient:
        nonlocal builds
        builds += 1
        return client

    monkeypatch.setattr(provider, "_build_client", fake_build)
    provider.complete(_request())
    provider.complete(_request())

    assert builds == 1


def test_refresh_credential_rebuilds_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenAIClient(_openai_response('{"decision":"IN_SCOPE"}'), None)
    settings = settings_from_mapping(
        {
            "model_provider": "openai_compatible",
            "model_id": "gpt-test",
            "model_api_key": "k",
        }
    )
    secrets = SecretResolver(settings=settings)
    provider = OpenAICompatibleProvider(settings=settings, secrets=secrets)

    builds = 0

    def fake_build(_credential: str | None) -> FakeOpenAIClient:
        nonlocal builds
        builds += 1
        return client

    monkeypatch.setattr(provider, "_build_client", fake_build)
    provider.complete(_request())
    provider._refresh_credential()
    provider.complete(_request())

    assert builds == 2


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        ("stop", "COMPLETED"),
        ("length", "MAX_OUTPUT_TOKENS"),
        ("content_filter", "CONTENT_FILTERED"),
        ("unknown_reason", "ERROR"),
    ],
)
def test_finish_reason_mapping(
    monkeypatch: pytest.MonkeyPatch, finish_reason: str, expected: str
) -> None:
    client = FakeOpenAIClient(
        _openai_response('{"decision":"IN_SCOPE"}', finish_reason), None
    )
    provider = _make_provider(monkeypatch, client=client)
    raw = provider._transport(_request())
    assert raw.finish_reason == expected


class _AuthError(Exception):
    pass


class _TimeoutError(Exception):
    pass


def test_auth_error_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenAIClient(None, _AuthError("bad key"))
    provider = _make_provider(monkeypatch, client=client)
    with pytest.raises(AuthProviderError):
        provider._transport(_request())


def test_timeout_error_is_classified_as_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeOpenAIClient(None, _TimeoutError("timed out"))
    provider = _make_provider(monkeypatch, client=client)
    with pytest.raises(RetryableProviderError):
        provider._transport(_request())
