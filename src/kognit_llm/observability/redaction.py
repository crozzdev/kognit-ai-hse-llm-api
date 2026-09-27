"""Redaction pass applied to every log string before emission (R14.32, R14.12-R14.15).

``Redactor`` replaces, with the literal ``[REDACTED]``:
1. exact matches of any resolved secret value (published by ``SecretResolver``);
2. database connection-string shapes carrying a user and password;
3. any substring following a ``Bearer`` token;
4. any contiguous run of >=32 characters drawn solely from the hex or base64
   alphabets.

The redactor holds resolved secret values as an opaque set so no secret is echoed
into a log entry, a response body or an exception message (R13.30).
"""

import re

__all__ = ["REDACTED", "Redactor"]

REDACTED = "[REDACTED]"

# A connection-string shape scheme://user:password@host...
_CONN_STRING = re.compile(r"[a-zA-Z][\w+.-]*://[^\s:@/]+:[^\s:@/]+@[^\s/]+")
# A Bearer token and the credential following it.
_BEARER = re.compile(r"(?i)(bearer)\s+\S+")
# A contiguous run of >=32 hex or base64 characters (tokens, hashes, keys).
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/=]{32,}")


class Redactor:
    """Applies the R14.32 redaction pass to arbitrary strings."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def publish(self, secret: str) -> None:
        """Register a resolved secret value to redact on sight (R14.32 rule 1)."""
        if secret:
            self._secrets.add(secret)

    def redact(self, text: str) -> str:
        """Return ``text`` with every sensitive shape replaced by ``[REDACTED]``."""
        if not text:
            return text
        result = text
        # 1. Exact resolved-secret matches (longest first, so substrings of a
        #    larger secret do not leave fragments behind).
        ordered_secrets = list(self._secrets)
        ordered_secrets.sort(key=len, reverse=True)
        for secret in ordered_secrets:
            if secret in result:
                result = result.replace(secret, REDACTED)
        # 2. Connection-string shapes.
        result = _CONN_STRING.sub(REDACTED, result)
        # 3. Post-Bearer substrings (keep the "Bearer" token itself).
        result = _BEARER.sub(rf"\1 {REDACTED}", result)
        # 4. Long hex/base64 runs.
        result = _LONG_TOKEN.sub(REDACTED, result)
        return result
