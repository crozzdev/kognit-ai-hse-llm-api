"""Request logger: one single-line JSON entry per chat request (R14.1-R14.38).

``RequestLogger.emit`` writes exactly one JSON object per request to stdout, on
one line with no unescaped newlines or carriage returns (R14.16), drawing only
from the closed field set of ``fields.LOG_FIELDS`` (R14.38). It applies the
pipeline redact -> size check -> truncate long string values with a
``truncated_fields`` list -> serialize (R14.29, R14.32), and on any serialization
or emission failure emits a minimal replacement entry without changing the
already-determined response (R14.28).
"""

import json
import sys
from collections.abc import Mapping
from typing import Any

from kognit_llm.observability.fields import LOG_FIELDS
from kognit_llm.observability.redaction import Redactor

__all__ = ["RequestLogger"]

_MAX_ENTRY_BYTES = 16384
_MAX_STRING_CHARS = 512


class RequestLogger:
    """Emits one redacted, single-line JSON entry per request (R14.1)."""

    def __init__(self, redactor: Redactor, stream: Any = None) -> None:
        self._redactor = redactor
        self._stream = stream if stream is not None else sys.stdout

    def emit(self, fields: Mapping[str, Any]) -> None:
        """Emit one log entry for a request, never raising (R14.1, R14.28)."""
        try:
            entry = self._build_entry(fields)
            line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
            self._write(line)
        except Exception:
            self._emit_fallback(fields)

    def _build_entry(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        # Keep only closed-set fields with a non-None value (R14.38).
        entry: dict[str, Any] = {
            key: value
            for key, value in fields.items()
            if key in LOG_FIELDS and value is not None
        }
        entry = self._redact_entry(entry)
        return self._truncate_entry(entry)

    def _redact_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (self._redactor.redact(value) if isinstance(value, str) else value)
            for key, value in entry.items()
        }

    def _truncate_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        serialized = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) <= _MAX_ENTRY_BYTES:
            return entry
        # Truncate every string value longer than 512 chars, naming them (R14.29).
        truncated: list[str] = []
        result: dict[str, Any] = {}
        for key, value in entry.items():
            if isinstance(value, str) and len(value) > _MAX_STRING_CHARS:
                result[key] = value[:_MAX_STRING_CHARS]
                truncated.append(key)
            else:
                result[key] = value
        if truncated:
            result["truncated_fields"] = truncated
        return result

    def _write(self, line: str) -> None:
        # Guarantee a single line: strip any embedded CR/LF (R14.16).
        safe = line.replace("\n", " ").replace("\r", " ")
        self._stream.write(safe + "\n")

    def _emit_fallback(self, fields: Mapping[str, Any]) -> None:
        """Minimal entry on emission failure; response is unchanged (R14.28)."""
        minimal = {
            "request_id": str(fields.get("request_id", "")),
            "timestamp": str(fields.get("timestamp", "")),
            "turn_outcome": str(fields.get("turn_outcome", "")),
            "error_category": "INTERNAL_ERROR",
        }
        try:
            self._write(json.dumps(minimal, separators=(",", ":")))
        except Exception:
            # Give up silently rather than propagate into the response path.
            return
