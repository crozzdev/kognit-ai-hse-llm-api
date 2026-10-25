"""Unit tests for kognit_llm.safety.scope_guard.

Cover the deterministic-first stage, the single model-assisted call, and the
fail-closed behavior on absent/invalid/out-of-set verdicts. The classifier is a
pure in-process stub (import boundary B1 keeps providers out of this package).
"""

from kognit_llm.safety import scope_guard
from kognit_llm.safety.scope_guard import (
    ScopeResult,
    ScopeVerdict,
    decide,
)


def test_public_all_exports() -> None:
    for name in scope_guard.__all__:
        assert hasattr(scope_guard, name)


# ── deterministic stage: no model call ──────────────────────────────────────


def test_deterministic_unsafe_short_circuits() -> None:
    result = decide("delete all the incidents")
    assert result == ScopeResult(decision="UNSAFE", model_called=False)


def test_deterministic_out_of_scope_short_circuits() -> None:
    result = decide("what were the sales figures")
    assert result.decision == "OUT_OF_SCOPE"
    assert result.model_called is False


def test_deterministic_runs_even_when_classifier_present() -> None:
    def classify(_message: str) -> "dict[str, object] | None":
        raise AssertionError("classifier must not be called")

    result = decide("drop the table", classify)
    assert result.decision == "UNSAFE"
    assert result.model_called is False


# ── no classifier: non-matching defaults to IN_SCOPE ────────────────────────


def test_no_classifier_non_matching_defaults_in_scope() -> None:
    result = decide("how many incidents last month")
    assert result == ScopeResult(decision="IN_SCOPE", model_called=False)


# ── model stage: valid verdicts ─────────────────────────────────────────────


def test_model_in_scope_verdict() -> None:
    def classify(_message: str) -> "dict[str, object] | None":
        return {"decision": "IN_SCOPE"}

    result = decide("a neutral question", classify)
    assert result == ScopeResult(decision="IN_SCOPE", model_called=True)


def test_model_unsafe_verdict() -> None:
    def classify(_message: str) -> "dict[str, object] | None":
        return {"decision": "UNSAFE"}

    result = decide("a neutral question", classify)
    assert result == ScopeResult(decision="UNSAFE", model_called=True)


def test_model_out_of_scope_verdict() -> None:
    def classify(_message: str) -> "dict[str, object] | None":
        return {"decision": "OUT_OF_SCOPE"}

    result = decide("a neutral question", classify)
    assert result == ScopeResult(decision="OUT_OF_SCOPE", model_called=True)


# ── model stage: fail-closed branches (R2.16) ───────────────────────────────


def test_model_none_fails_closed() -> None:
    def classify(_message: str) -> "dict[str, object] | None":
        return None

    result = decide("a neutral question", classify)
    assert result == ScopeResult(decision="OUT_OF_SCOPE", model_called=True)


def test_model_missing_field_fails_closed() -> None:
    def classify(_message: str) -> "dict[str, object] | None":
        return {}

    result = decide("a neutral question", classify)
    assert result == ScopeResult(decision="OUT_OF_SCOPE", model_called=True)


def test_model_extra_field_rejected_fails_closed() -> None:
    # extra="forbid" makes an unexpected key invalidate the verdict.
    def classify(_message: str) -> "dict[str, object] | None":
        return {"decision": "IN_SCOPE", "unexpected": 1}

    result = decide("a neutral question", classify)
    assert result == ScopeResult(decision="OUT_OF_SCOPE", model_called=True)


def test_model_out_of_set_value_fails_closed() -> None:
    def classify(_message: str) -> "dict[str, object] | None":
        return {"decision": "MAYBE"}

    result = decide("a neutral question", classify)
    assert result == ScopeResult(decision="OUT_OF_SCOPE", model_called=True)


# ── ScopeVerdict model directly ─────────────────────────────────────────────


def test_scope_verdict_valid() -> None:
    verdict = ScopeVerdict.model_validate({"decision": "IN_SCOPE"})
    assert verdict.decision == "IN_SCOPE"
