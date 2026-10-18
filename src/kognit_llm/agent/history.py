"""Prior-turn messages for model calls (conversation continuity, R12).

``context_messages`` turns the opaque ``conversation_context`` turn records into
an ordered tuple of ``Message`` objects (user then assistant, oldest first) that
a node can prepend to its model request so the model understands references to
earlier turns (for example a follow-up like "and only the night shift?"). Records
are read defensively via ``getattr`` so any object shape is tolerated; a record
missing either side is skipped.
"""

from collections.abc import Sequence

from kognit_llm.providers.base import Message

__all__ = ["context_messages"]


def context_messages(
    conversation_context: Sequence[object], *, max_turns: int
) -> tuple[Message, ...]:
    """Return prior turns as ``(user, assistant)`` message pairs, oldest first.

    At most ``max_turns`` most-recent turns are included. A turn whose user or
    assistant text is missing or empty is skipped.
    """
    recent = list(conversation_context)[-max_turns:] if max_turns > 0 else []
    messages: list[Message] = []
    for record in recent:
        user_text = getattr(record, "user_message", None)
        assistant_text = getattr(record, "answer_text", None)
        if not user_text or not assistant_text:
            continue
        messages.append(Message(role="user", content=str(user_text)))
        messages.append(Message(role="assistant", content=str(assistant_text)))
    return tuple(messages)
