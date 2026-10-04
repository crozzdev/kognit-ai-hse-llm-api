"""Per-turn telemetry side-channel (D10, R16.17, R14.23-R14.25).

Observability data — per-stage durations, token counts, provider-call counts,
connection-acquisition time, truncation and cold-start flags — is kept here,
outside ``TurnState``, so the graph state stays exactly the 20 fields of R10.18
(D10). The node guard writes ``stage_ms`` around each node; the logger reads this
side-channel to build the single request log entry (M-14).
"""

from dataclasses import dataclass, field

__all__ = ["TurnTelemetry"]


@dataclass(slots=True)
class TurnTelemetry:
    """Mutable per-turn observability data, carried alongside ``TurnState``."""

    stage_ms: dict[str, int] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider_calls: dict[str, int] = field(default_factory=dict)
    connection_acquisition_ms: int | None = None
    result_truncated: bool = False
    cold_start: bool = False

    def record_stage(self, node: str, elapsed_ms: int) -> None:
        """Record one node's elapsed milliseconds (R16.17)."""
        self.stage_ms[node] = elapsed_ms

    def record_provider_call(
        self, call_type: str, prompt_tokens: int, completion_tokens: int
    ) -> None:
        """Accumulate one provider call's counts (R14.23-R14.24)."""
        self.provider_calls[call_type] = self.provider_calls.get(call_type, 0) + 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens

    @property
    def model_call_count(self) -> int:
        """Total provider calls across all call types this turn."""
        return sum(self.provider_calls.values())
