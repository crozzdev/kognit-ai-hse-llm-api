"""Deterministic stub model provider for tests (R11.30, R17.30-R17.32).

``StubProvider`` holds one canned output per ``CallType``, counts invocations per
call type, fails when an undeclared call type is requested, returns identical
output for identical requests, and may hold SQL that violates the firewall rules
of Requirement 6. It performs no network I/O (R11.30).
"""

from collections import defaultdict

from pydantic import BaseModel

from kognit_llm.providers.base import (
    CallType,
    CompletionRequest,
    CompletionResult,
)

__all__ = ["StubProvider"]


class StubProvider:
    """A canned, deterministic ``ModelProvider`` for tests (no network)."""

    provider_id = "stub"

    def __init__(self) -> None:
        self._canned: dict[CallType, BaseModel] = {}
        self._counts: dict[CallType, int] = defaultdict(int)

    def declare(self, call_type: CallType, output: BaseModel) -> None:
        """Declare the canned output for one call type (R17.30)."""
        self._canned[call_type] = output

    def invocation_count(self, call_type: CallType) -> int:
        """Return how many times ``call_type`` was requested (R17.32)."""
        return self._counts[call_type]

    def complete[T: BaseModel](
        self, request: CompletionRequest[T]
    ) -> CompletionResult[T]:
        """Return the declared canned output for the request's call type.

        Fails the test with an error naming the call type when no output was
        declared for it (R17.31). Identical requests yield identical output.
        """
        call_type = request.call_type
        self._counts[call_type] += 1
        if call_type not in self._canned:
            raise AssertionError(
                f"StubProvider has no canned output for call type '{call_type}'"
            )
        output = self._canned[call_type]
        if not isinstance(output, request.output_model):
            raise AssertionError(
                f"declared output for '{call_type}' is not a "
                f"{request.output_model.__name__}"
            )
        return CompletionResult(
            output=output,
            prompt_tokens=0,
            completion_tokens=0,
            finish_reason="COMPLETED",
            provider_request_id="",
        )
