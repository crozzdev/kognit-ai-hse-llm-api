"""Conversation store protocol and turn record (R12.19, R12.26-R12.27).

``TurnRecord`` is the frozen, one-per-turn record retained per conversation. It
excludes generated/executed SQL, schema context, warehouse rows, narrative text
and PII (R12.23); the resolved analytics intent is retained as a serialized value
of at most 2000 characters, omitted when longer (R12.26-R12.27). ``char_size`` is
the basis of the per-turn and total character budgets (R12.28-R12.30).

``ConversationStore`` is the storage interface (R12.19), keyed by
``(user_id, conversation_id)`` so a multi-user implementation needs no interface
change.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

__all__ = ["ANALYTICS_INTENT_MAX_CHARS", "ConversationStore", "TurnRecord"]

# The resolved analytics intent is retained only when its serialization fits
# (R12.26); a longer one is omitted with every other field retained (R12.27).
ANALYTICS_INTENT_MAX_CHARS = 2000


class TurnRecord(BaseModel):
    """One retained conversation turn (R12.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_message: str
    answer_text: str
    scope_decision: str
    intent: str
    analytics_intent_json: str | None = None
    requested_at: datetime
    completed_at: datetime

    def char_size(self) -> int:
        """Total retained character count of this record (R12.28)."""
        return (
            len(self.user_message)
            + len(self.answer_text)
            + len(self.scope_decision)
            + len(self.intent)
            + (len(self.analytics_intent_json) if self.analytics_intent_json else 0)
            + len(self.requested_at.isoformat())
            + len(self.completed_at.isoformat())
        )


class ConversationStore(Protocol):
    """The conversation storage interface (R12.19)."""

    def get_context(
        self, user_id: str, conversation_id: str
    ) -> tuple[TurnRecord, ...]:
        """Return the retained turns in chronological order, or empty (R12.3-R12.4)."""
        ...

    def append_turn(
        self, user_id: str, conversation_id: str, turn: TurnRecord
    ) -> int:
        """Append one turn; return the retained turn count afterward (R12.19)."""
        ...

    def purge_expired(self) -> int:
        """Remove expired conversations; return the count removed (R12.19)."""
        ...
