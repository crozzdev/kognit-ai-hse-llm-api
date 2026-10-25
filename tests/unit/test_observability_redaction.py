"""Unit tests for the log redaction pass (src/kognit_llm/observability).

Covers each redaction rule: published secret values, connection-string shapes,
post-Bearer credentials, and long hex/base64 runs, plus the empty-string and
no-match passthroughs (R14.32, R14.12-R14.15).
"""

from kognit_llm.observability.redaction import REDACTED, Redactor


def test_empty_string_passthrough():
    assert Redactor().redact("") == ""


def test_plain_text_unchanged():
    r = Redactor()
    assert r.redact("nothing sensitive here") == "nothing sensitive here"


def test_published_secret_is_redacted():
    r = Redactor()
    r.publish("super-secret-value")
    assert r.redact("token=super-secret-value end") == f"token={REDACTED} end"


def test_publish_ignores_empty_secret():
    r = Redactor()
    r.publish("")
    # No secret registered, so an empty substring does not redact everything.
    assert r.redact("hello") == "hello"


def test_longest_secret_redacted_first():
    r = Redactor()
    r.publish("abc")
    r.publish("abcdef")
    assert r.redact("value=abcdef") == f"value={REDACTED}"


def test_connection_string_shape_redacted():
    r = Redactor()
    text = "postgresql://user:p4ss@db.example.com:5432/warehouse"
    out = r.redact(text)
    # The user:password@host run is replaced; neither credential survives.
    assert "user" not in out
    assert "p4ss" not in out
    assert out.startswith(REDACTED)


def test_bearer_token_redacted_keeping_keyword():
    r = Redactor()
    out = r.redact("Authorization: Bearer abc.def.ghi")
    assert out == f"Authorization: Bearer {REDACTED}"


def test_long_hex_or_base64_run_redacted():
    r = Redactor()
    token = "A1b2" * 10  # 40 chars, base64/hex alphabet
    assert r.redact(f"key {token} tail") == f"key {REDACTED} tail"
