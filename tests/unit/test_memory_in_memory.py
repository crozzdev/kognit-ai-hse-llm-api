"""Unit tests for the in-memory conversation store (src/kognit_llm/memory).

Drives the LRU + TTL + turn-max + char-budget bounding rules with an injected
frozen clock so expiry and eviction are deterministic (R12.1-R12.37).
"""

from datetime import datetime, timedelta

from kognit_llm.memory.in_memory import InMemoryConversationStore
from kognit_llm.memory.store import TurnRecord

_BASE = datetime(2026, 1, 1, 12, 0, 0)


class _Clock:
    """A mutable clock the store reads via ``now``."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


def _turn(message: str = "hi", answer: str = "ok", at: datetime = _BASE) -> TurnRecord:
    return TurnRecord(
        user_message=message,
        answer_text=answer,
        scope_decision="IN_SCOPE",
        intent="DATA_QUERY",
        requested_at=at,
        completed_at=at,
    )


def _store(clock, **overrides):
    params = {
        "turn_max": 10,
        "conversation_max": 5,
        "ttl_seconds": 1800,
        "char_budget": 100_000,
        "clock": clock,
    }
    params.update(overrides)
    return InMemoryConversationStore(**params)


def test_empty_context_is_empty_tuple():
    store = _store(_Clock(_BASE))
    assert store.get_context("DEMO", "c1") == ()


def test_append_then_get_returns_turn():
    clock = _Clock(_BASE)
    store = _store(clock)
    count = store.append_turn("DEMO", "c1", _turn())
    assert count == 1
    turns = store.get_context("DEMO", "c1")
    assert len(turns) == 1
    assert turns[0].user_message == "hi"


def test_turns_returned_in_chronological_order():
    clock = _Clock(_BASE)
    store = _store(clock)
    store.append_turn("DEMO", "c1", _turn(message="first"))
    clock.advance(1)
    store.append_turn("DEMO", "c1", _turn(message="second", at=clock.now))
    turns = store.get_context("DEMO", "c1")
    assert [t.user_message for t in turns] == ["first", "second"]


def test_ttl_expiry_clears_conversation_on_get():
    clock = _Clock(_BASE)
    store = _store(clock, ttl_seconds=60)
    store.append_turn("DEMO", "c1", _turn(at=clock.now))
    clock.advance(61)
    assert store.get_context("DEMO", "c1") == ()


def test_turn_max_trim_keeps_most_recent():
    clock = _Clock(_BASE)
    store = _store(clock, turn_max=2)
    for i in range(4):
        store.append_turn("DEMO", "c1", _turn(message=f"m{i}", at=clock.now))
        clock.advance(1)
    turns = store.get_context("DEMO", "c1")
    assert [t.user_message for t in turns] == ["m2", "m3"]


def test_conversation_count_lru_eviction():
    clock = _Clock(_BASE)
    store = _store(clock, conversation_max=2)
    store.append_turn("DEMO", "c1", _turn(at=clock.now))
    clock.advance(1)
    store.append_turn("DEMO", "c2", _turn(at=clock.now))
    clock.advance(1)
    # Appending a third conversation evicts the least-recently-used (c1).
    store.append_turn("DEMO", "c3", _turn(at=clock.now))
    assert store.get_context("DEMO", "c1") == ()
    assert len(store.get_context("DEMO", "c2")) == 1
    assert len(store.get_context("DEMO", "c3")) == 1


def test_char_budget_evicts_older_conversations():
    clock = _Clock(_BASE)
    big = "x" * 200
    store = _store(clock, conversation_max=10, char_budget=500)
    store.append_turn("DEMO", "c1", _turn(answer=big, at=clock.now))
    clock.advance(1)
    store.append_turn("DEMO", "c2", _turn(answer=big, at=clock.now))
    clock.advance(1)
    # The third big turn pushes the total over budget; the LRU conversation goes.
    store.append_turn("DEMO", "c3", _turn(answer=big, at=clock.now))
    assert store.get_context("DEMO", "c1") == ()
    assert len(store.get_context("DEMO", "c3")) == 1


def test_char_budget_trims_turns_of_sole_conversation():
    clock = _Clock(_BASE)
    big = "x" * 200
    store = _store(clock, turn_max=100, char_budget=500)
    for _ in range(5):
        store.append_turn("DEMO", "c1", _turn(answer=big, at=clock.now))
        clock.advance(1)
    turns = store.get_context("DEMO", "c1")
    total = sum(t.char_size() for t in turns)
    assert total <= 500
    assert len(turns) >= 1


def test_purge_expired_returns_count():
    clock = _Clock(_BASE)
    store = _store(clock, ttl_seconds=60)
    store.append_turn("DEMO", "c1", _turn(at=clock.now))
    store.append_turn("DEMO", "c2", _turn(at=clock.now))
    clock.advance(61)
    assert store.purge_expired() == 2
    assert store.get_context("DEMO", "c1") == ()


def test_append_after_expiry_starts_fresh_conversation():
    clock = _Clock(_BASE)
    store = _store(clock, ttl_seconds=60)
    store.append_turn("DEMO", "c1", _turn(message="old", at=clock.now))
    clock.advance(61)
    count = store.append_turn("DEMO", "c1", _turn(message="new", at=clock.now))
    assert count == 1
    turns = store.get_context("DEMO", "c1")
    assert [t.user_message for t in turns] == ["new"]
