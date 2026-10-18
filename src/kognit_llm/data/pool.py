"""Warehouse connection pool with lazy open (R7.22-R7.26, R16.21-R16.22).

``build_pool`` constructs a ``psycopg_pool.ConnectionPool`` sized from
configuration, with the read-only ``configure`` hook, a liveness check on
checkout, and ``open=False`` so the pool opens on first warehouse use rather than
at import time (R16.21-R16.22). The pool persists across invocations of the same
execution environment (R7.22).

Import boundary B3: imports psycopg_pool; lives under ``data/**``.
"""

from typing import TYPE_CHECKING

from psycopg_pool import ConnectionPool

from kognit_llm.data.session import build_conninfo, configure

if TYPE_CHECKING:
    from kognit_llm.config.secrets import DbCredentials
    from kognit_llm.config.settings import Settings

__all__ = ["build_pool"]


def build_pool(settings: "Settings", creds: "DbCredentials") -> ConnectionPool:
    """Build the warehouse connection pool, closed until first use (R16.21).

    ``min_size``/``max_size`` come from configuration (default 1/2, R7.23), the
    acquisition ``timeout`` from the connect timeout (R7.24), each connection is
    configured read-only on checkout (R7.3), and ``check`` validates liveness
    before a pooled connection is handed out (R7.25-R7.26).
    """
    return ConnectionPool(
        conninfo=build_conninfo(settings, creds),
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        timeout=settings.db_connect_timeout_ms / 1000,
        configure=configure,
        check=ConnectionPool.check_connection,
        open=False,
    )
