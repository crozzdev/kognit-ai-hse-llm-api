"""Unit tests for the shared provider execution policy (R11.6, R11.16-R11.22, R11.26).

These exercise ``ProviderBase.complete`` and ``_parse`` through a fake transport
that implements only ``_transport``/``_refresh_credential``, so the retry,
credential-refresh, token-ceiling, finish-reason and parse/repair policy is
tested independently of any SDK. No network I/O occurs (conftest blocks sockets).
"""

from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from kognit_llm.providers.base import (
    AuthProviderError,
    CompletionRequest,
    Message,
    ProviderBase,
    ProviderOutputError,
    RawCompletion,
    RetryableProviderError,
    _extract_first_json_object,
)


class Verdict(BaseModel):
    """A minimal structured output for the tests."""

    decision: str


class FakeProvider(ProviderBase):
    """Drives ``ProviderBase`` from a scripted list of transport outcomes.

    Each item in ``script`` is either a ``RawCompletion`` to return or an
    ``Exception`` to raise. ``transport_calls`` and ``refresh_calls`` record how
    the shared policy exercised the transport seam.
    """

    provider_id = "fake"

    def __init__(
        self, script: Sequence[RawCompletion | Exception], *, max_retries: int = 2
    ) -> None:
        super().__init__(max_retries=max_retries)
        self._script = list(script)
        self.transport_calls = 0
        self.refresh_calls = 0

    def _transport(self, request: CompletionRequest[BaseModel]) -> RawCompletion:
        outcome = self._script[min(self.transport_calls, len(self._script) - 1)]
        self.transport_calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _refresh_credential(self) -> None:
        self.refresh_calls += 1


def _request() -> CompletionRequest[Verdict]:
    return CompletionRequest[Verdict](
        call_type="scope",
        system_instruction="",
        messages=(Message(role="user", content="x"),),
        output_model=Verdict,
        temperature=0.0,
        max_output_tokens=32,
        timeout_ms=1000,
        request_id="req-1",
    )


def _completed(text: str) -> RawCompletion:
    return RawCompletion(
        text=text,
        prompt_tokens=3,
        completion_tokens=5,
        finish_reason="COMPLETED",
        provider_request_id="pid-1",
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise retry backoff so timing does not slow the suite."""
    monkeypatch.setattr("kognit_llm.providers.base.time.sleep", lambda _seconds: None)


# ── _extract_first_json_object ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"decision":"IN_SCOPE"}', '{"decision":"IN_SCOPE"}'),
        (
            '{"decision":"IN_SCOPE"}\n\n**Reasoning:** because...',
            '{"decision":"IN_SCOPE"}',
        ),
        ('prefix {"a": {"b": 1}} suffix', '{"a": {"b": 1}}'),
        ('{"s": "a}b{c"} tail', '{"s": "a}b{c"}'),
        (r'{"s": "esc\"aped}"} x', r'{"s": "esc\"aped}"}'),
        ("no json here", None),
        ('{"unbalanced": 1', None),
        ("", None),
    ],
)
def test_extract_first_json_object(text: str, expected: str | None) -> None:
    assert _extract_first_json_object(text) == expected


# ── parse / repair policy ─────────────────────────────────────────────────────


def test_complete_parses_pure_json() -> None:
    provider = FakeProvider([_completed('{"decision":"IN_SCOPE"}')])
    result = provider.complete(_request())
    assert result.output.decision == "IN_SCOPE"
    assert result.prompt_tokens == 3
    assert result.completion_tokens == 5
    assert result.finish_reason == "COMPLETED"
    assert result.provider_request_id == "pid-1"
    assert provider.transport_calls == 1


def test_complete_parses_json_wrapped_in_markdown() -> None:
    """The bug fix: a valid object followed by prose still parses (no repair)."""
    provider = FakeProvider(
        [_completed('{"decision":"IN_SCOPE"}\n\n**Reasoning:** it is HSE analytics.')]
    )
    result = provider.complete(_request())
    assert result.output.decision == "IN_SCOPE"
    # Parsed on the first call; no repair reissue was needed.
    assert provider.transport_calls == 1


def test_complete_repairs_once_then_succeeds() -> None:
    """A first unparseable reply triggers exactly one repair reissue (R11.16)."""
    provider = FakeProvider(
        [_completed("not json at all"), _completed('{"decision":"UNSAFE"}')]
    )
    result = provider.complete(_request())
    assert result.output.decision == "UNSAFE"
    assert provider.transport_calls == 2


def test_complete_raises_when_repair_also_fails() -> None:
    """Both the first reply and the repair fail to parse -> ProviderOutputError."""
    provider = FakeProvider([_completed("still not json"), _completed("also not json")])
    with pytest.raises(ProviderOutputError):
        provider.complete(_request())
    assert provider.transport_calls == 2


# ── finish-reason policy ──────────────────────────────────────────────────────


def test_complete_content_filtered_raises_without_parse() -> None:
    provider = FakeProvider([RawCompletion("", 0, 0, "CONTENT_FILTERED")])
    with pytest.raises(ProviderOutputError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.finish_reason == "CONTENT_FILTERED"
    assert provider.transport_calls == 1


def test_complete_error_finish_reason_raises() -> None:
    provider = FakeProvider([RawCompletion("", 0, 0, "ERROR")])
    with pytest.raises(ProviderOutputError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.finish_reason == "ERROR"


def test_complete_reissues_once_on_max_output_tokens() -> None:
    """MAX_OUTPUT_TOKENS reissues once; a good second reply parses (R11.21)."""
    provider = FakeProvider(
        [
            RawCompletion("", 0, 0, "MAX_OUTPUT_TOKENS"),
            _completed('{"decision":"IN_SCOPE"}'),
        ]
    )
    result = provider.complete(_request())
    assert result.output.decision == "IN_SCOPE"
    assert provider.transport_calls == 2


def test_complete_raises_when_max_output_tokens_twice() -> None:
    provider = FakeProvider(
        [
            RawCompletion("", 0, 0, "MAX_OUTPUT_TOKENS"),
            RawCompletion("", 0, 0, "MAX_OUTPUT_TOKENS"),
        ]
    )
    with pytest.raises(ProviderOutputError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.finish_reason == "MAX_OUTPUT_TOKENS"


# ── retry / refresh policy ────────────────────────────────────────────────────


def test_complete_retries_retryable_error_then_succeeds() -> None:
    """A retryable transport error is retried within the max-retries budget (R11.6)."""
    provider = FakeProvider(
        [RetryableProviderError("timeout"), _completed('{"decision":"IN_SCOPE"}')],
        max_retries=2,
    )
    result = provider.complete(_request())
    assert result.output.decision == "IN_SCOPE"
    assert provider.transport_calls == 2


def test_complete_exhausts_retries_and_raises() -> None:
    provider = FakeProvider([RetryableProviderError("timeout")], max_retries=2)
    with pytest.raises(RetryableProviderError):
        provider.complete(_request())
    # Initial attempt plus two retries.
    assert provider.transport_calls == 3


def test_complete_refreshes_credential_once_on_auth_error() -> None:
    """One AuthProviderError triggers a single refresh then a retry (R11.26)."""
    provider = FakeProvider(
        [AuthProviderError("denied"), _completed('{"decision":"IN_SCOPE"}')]
    )
    result = provider.complete(_request())
    assert result.output.decision == "IN_SCOPE"
    assert provider.refresh_calls == 1
    assert provider.transport_calls == 2


def test_complete_raises_when_auth_error_persists_after_refresh() -> None:
    provider = FakeProvider(
        [AuthProviderError("denied"), AuthProviderError("still denied")]
    )
    with pytest.raises(AuthProviderError):
        provider.complete(_request())
    # Exactly one refresh; the second auth error is not retried again.
    assert provider.refresh_calls == 1
    assert provider.transport_calls == 2
