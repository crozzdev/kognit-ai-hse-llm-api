"""HSE scope guard: deterministic stage then at most one model call (R2.15-R2.17).

``decide`` renders the scope decision in two stages (D12):

1. A deterministic rule stage that issues zero model calls and matches the
   Spanish/English patterns of ``scope_rules`` with precedence
   UNSAFE -> OUT_OF_SCOPE (R2.17).
2. Only when the deterministic stage matches no rejection category, exactly one
   model-assisted classification call, failing closed to ``OUT_OF_SCOPE`` on an
   absent, invalid or out-of-set verdict (R2.16).

Import boundary B1: ``safety/**`` must not import ``providers/**``. The guard
therefore takes a ``classify`` callable that performs the single model call and
returns the raw decision string (or ``None`` on failure); the wiring node in
``agent/nodes/`` supplies it, keeping the provider dependency out of this package.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from kognit_llm.safety.scope_rules import match_category

__all__ = ["ScopeDecision", "ScopeResult", "ScopeVerdict", "decide"]

ScopeDecision = Literal["IN_SCOPE", "OUT_OF_SCOPE", "UNSAFE"]
_VALID_DECISIONS = frozenset({"IN_SCOPE", "OUT_OF_SCOPE", "UNSAFE"})

# The classify callable returns the model's raw structured output as a mapping
# (or None when the model call failed / produced no verdict).
Classifier = Callable[[str], "dict[str, object] | None"]


class ScopeVerdict(BaseModel):
    """The model-assisted scope classification output (R2.16)."""

    model_config = ConfigDict(extra="forbid")

    decision: ScopeDecision


@dataclass(frozen=True, slots=True)
class ScopeResult:
    """The guard outcome and whether the model stage was used."""

    decision: ScopeDecision
    model_called: bool


def decide(message: str, classify: Classifier | None = None) -> ScopeResult:
    """Return the HSE scope decision for ``message`` (R2.15-R2.17).

    The deterministic stage runs first with no model call. If it matches a
    rejection category, that decision is returned immediately. Otherwise a single
    model call is made through ``classify``; any absent, invalid or out-of-set
    verdict fails closed to ``OUT_OF_SCOPE`` (R2.16). With no ``classify`` (the
    stub-free path), a non-matching message defaults to ``IN_SCOPE`` (R2.17).
    """
    deterministic = match_category(message)
    if deterministic is not None:
        return ScopeResult(decision=deterministic, model_called=False)

    if classify is None:
        return ScopeResult(decision="IN_SCOPE", model_called=False)

    raw = classify(message)
    verdict = _parse_verdict(raw)
    if verdict is None:
        return ScopeResult(decision="OUT_OF_SCOPE", model_called=True)
    return ScopeResult(decision=verdict.decision, model_called=True)


def _parse_verdict(raw: "dict[str, object] | None") -> ScopeVerdict | None:
    """Validate the raw model output into a ``ScopeVerdict`` or None (R2.16)."""
    if raw is None:
        return None
    try:
        verdict = ScopeVerdict.model_validate(raw)
    except ValidationError:
        return None
    if verdict.decision not in _VALID_DECISIONS:
        return None
    return verdict
