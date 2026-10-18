"""In-memory conversation store (R12.1-R12.37, R16.12).

An ``OrderedDict`` keyed by ``(user_id, conversation_id)`` used as an LRU, guarded
by an ``RLock`` for the concurrent-append serialization of R12.35. On append, the
bounding rules are applied in the R12.32 order: TTL expiry first, then
per-conversation turn-maximum trim, then conversation-count LRU eviction, then
total-character-budget LRU eviction. ``get_context`` sets the LRU access
timestamp (R12.33) but leaves the expiry-basis timestamp untouched (R12.15), and
returns the retained turns in chronological order.

Conversations are held per execution environment only and start empty (R12.18,
R12.20). The clock is injected so tests drive TTL/eviction with a frozen clock.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from kognit_llm.memory.store import TurnRecord

__all__ = ["InMemoryConversationStore"]

_Key = tuple[str, str]


@dataclass
class _Conversation:
    """Mutable per-conversation state guarded by the store's lock."""

    turns: list[TurnRecord] = field(default_factory=list)
    last_access: datetime | None = None
    # Expiry is measured from the most recent turn's completion timestamp (R12.15).
    expiry_basis: datetime | None = None

    def char_size(self) -> int:
        return sum(turn.char_size() for turn in self.turns)


class InMemoryConversationStore:
    """LRU + TTL + budget-bounded conversation store for one execution environment."""

    def __init__(
        self,
        *,
        turn_max: int,
        conversation_max: int,
        ttl_seconds: int,
        char_budget: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._turn_max = turn_max
        self._conversation_max = conversation_max
        self._ttl_seconds = ttl_seconds
        self._char_budget = char_budget
        self._clock = clock
        self._lock = threading.RLock()
        self._store: OrderedDict[_Key, _Conversation] = OrderedDict()

    def get_context(
        self, user_id: str, conversation_id: str
    ) -> tuple[TurnRecord, ...]:
        """Return retained turns chronologically, else empty (R12.3-R12.4)."""
        key = (user_id, conversation_id)
        now = self._clock()
        with self._lock:
            conversation = self._store.get(key)
            if conversation is None or self._is_expired(conversation, now):
                if conversation is not None:
                    del self._store[key]
                return ()
            # Set the LRU access timestamp, not the expiry basis (R12.15, R12.33).
            conversation.last_access = now
            self._store.move_to_end(key)
            return tuple(conversation.turns)

    def append_turn(
        self, user_id: str, conversation_id: str, turn: TurnRecord
    ) -> int:
        """Append one turn and apply the R12.32 bounding order; return turn count."""
        key = (user_id, conversation_id)
        now = self._clock()
        with self._lock:
            # 1. Expire time-to-live-elapsed conversations first (R12.32).
            self._purge_expired_locked(now)

            conversation = self._store.get(key)
            if conversation is None or self._is_expired(conversation, now):
                conversation = _Conversation()
                self._store[key] = conversation
            self._store.move_to_end(key)

            conversation.turns.append(turn)
            conversation.last_access = now
            conversation.expiry_basis = turn.completed_at

            # 2. Per-conversation turn-maximum trim (R12.11).
            if len(conversation.turns) > self._turn_max:
                overflow = len(conversation.turns) - self._turn_max
                del conversation.turns[:overflow]

            # 3. Conversation-count LRU eviction (R12.14).
            while len(self._store) > self._conversation_max:
                self._store.popitem(last=False)

            # 4. Total-character-budget LRU eviction (R12.31).
            self._enforce_char_budget_locked(key)

            survivor = self._store.get(key)
            return len(survivor.turns) if survivor is not None else 0

    def purge_expired(self) -> int:
        """Remove expired conversations; return the count removed (R12.19)."""
        now = self._clock()
        with self._lock:
            return self._purge_expired_locked(now)

    # ── Internal (lock held) ─────────────────────────────────────────────────

    def _is_expired(self, conversation: _Conversation, now: datetime) -> bool:
        if conversation.expiry_basis is None:
            return False
        elapsed = (now - conversation.expiry_basis).total_seconds()
        return elapsed >= self._ttl_seconds

    def _purge_expired_locked(self, now: datetime) -> int:
        expired = [
            key
            for key, conversation in self._store.items()
            if self._is_expired(conversation, now)
        ]
        for key in expired:
            del self._store[key]
        return len(expired)

    def _enforce_char_budget_locked(self, appended_key: _Key) -> None:
        def total() -> int:
            return sum(c.char_size() for c in self._store.values())

        # Evict whole conversations in ascending last-access (LRU) order, keeping
        # the just-appended conversation as the last one standing (R12.31).
        while total() > self._char_budget and len(self._store) > 1:
            oldest = next(iter(self._store))
            if oldest == appended_key:
                break
            del self._store[oldest]

        # When only the appended conversation remains, drop its oldest turns until
        # the total is at or below the budget (R12.31).
        survivor = self._store.get(appended_key)
        if survivor is not None:
            while total() > self._char_budget and len(survivor.turns) > 1:
                del survivor.turns[0]
