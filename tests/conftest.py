"""Shared test configuration: no-sockets guard, Hypothesis profile, settings.

Global policies (design §Global policies):
- No sockets. A session-scoped autouse fixture replaces ``socket.socket`` with a
  raising stub, so any attempted real network I/O fails the test that attempted
  it (R17.29). The in-process ASGI ``TestClient`` does not open real sockets, so
  it is unaffected.
- No AWS credentials required (R15.26); every ``Settings`` used in tests is built
  with ``settings_from_mapping``.
- A shared Hypothesis profile registers ``max_examples=100, deadline=None``
  (R16.32); property tests also declare it explicitly.
"""

import socket
from collections.abc import Callable, Iterator

import pytest
from hypothesis import HealthCheck, settings

from kognit_llm.config.settings import Settings, settings_from_mapping

settings.register_profile(
    "kognit",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("kognit")


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


def _is_loopback(address: object) -> bool:
    """True when ``address`` targets loopback (event-loop self-pipe, TestClient)."""
    if isinstance(address, tuple) and address:
        host = address[0]
        return isinstance(host, str) and host in _LOOPBACK_HOSTS
    # Non-inet families (AF_UNIX self-pipes, fds) are left alone.
    return not isinstance(address, tuple)


def _guarded(original: Callable[..., object]) -> Callable[..., object]:
    def guard(self: object, address: object = None, *args: object) -> object:
        if address is not None and not _is_loopback(address):
            raise RuntimeError(
                "outbound network connections are disabled in tests "
                "(design §Global policies, R17.29)"
            )
        return original(self, address, *args)

    return guard


@pytest.fixture(scope="session", autouse=True)
def _no_sockets() -> Iterator[None]:
    """Block outbound non-loopback connections without breaking the ASGI client.

    Real network egress fails the test that attempted it (R17.29); loopback and
    non-inet self-pipes stay usable so the in-process ``TestClient`` and the
    event loop work on every platform.
    """
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    socket.socket.connect = _guarded(original_connect)  # ty: ignore[invalid-assignment]
    socket.socket.connect_ex = _guarded(original_connect_ex)  # ty: ignore[invalid-assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex


@pytest.fixture
def test_settings() -> Settings:
    """A valid ``Settings`` built without environment or AWS access."""
    return settings_from_mapping({})
