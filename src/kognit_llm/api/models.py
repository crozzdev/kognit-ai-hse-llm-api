"""HTTP contract models for the chat endpoint and health routes (R1).

``ChatRequest`` ignores undeclared fields so a client-supplied ``user_id`` or
``request_id`` is dropped (R1.8, R1.15). ``ChatResponse`` fixes ``user_id`` to
``DEMO`` and enumerates ``intent`` and ``scope_decision``; ``query_executed`` is
omitted from the serialized body when ``None`` via ``response_model_exclude_none``
(R1.13). ``ErrorBody`` carries exactly the three fields of the uniform failure
body so two failures of one category differ only in ``request_id`` (R13.32).
"""

import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CONVERSATION_ID_PATTERN",
    "ChatRequest",
    "ChatResponse",
    "ErrorBody",
    "HealthBody",
    "normalize_message",
]

CONVERSATION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


def normalize_message(raw: str) -> str:
    """Return ``raw`` NFC-normalized with leading/trailing whitespace removed.

    This is the transformation R1.4-R1.5 and R1.15 require before the length
    bound is applied and before the value reaches the agent.
    """
    return unicodedata.normalize("NFC", raw).strip()


class ChatRequest(BaseModel):
    """One inbound chat message plus an optional conversation identifier."""

    # extra="ignore" satisfies R1.8 (supplied user_id) and R1.15 (request_id).
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)

    message: Annotated[str, Field(min_length=1)]
    conversation_id: (
        Annotated[str, Field(pattern=CONVERSATION_ID_PATTERN)] | None
    ) = None


class ChatResponse(BaseModel):
    """The successful chat response body (R1.9-R1.13)."""

    response: Annotated[str, Field(min_length=1)]
    conversation_id: str
    user_id: Literal["DEMO"] = "DEMO"
    intent: Literal["DATA_QUERY", "GENERAL_CHAT", "CLARIFICATION_NEEDED", "REJECTED"]
    request_id: str
    scope_decision: Literal["IN_SCOPE", "OUT_OF_SCOPE", "UNSAFE"]
    # Omitted from the body unless expose_executed_sql and a query ran (R1.12-R1.14).
    query_executed: str | None = None


class ErrorBody(BaseModel):
    """The uniform failure body: fixed message per category (R13.9, R13.32)."""

    error_category: str
    message: str
    request_id: str


class HealthBody(BaseModel):
    """The ``GET /health`` body reporting per-dependency status (R1.19)."""

    warehouse: str
    model_provider: str
    configuration: str
    schema_verification: str
    overall: str
