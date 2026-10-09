"""Read-only warehouse session and transaction setup (R7.1-R7.4, R7.20).

``build_conninfo`` produces a psycopg connection string that pins the read-only
session characteristic and the statement timeout from the first statement,
avoiding an extra round trip: ``options`` carries
``default_transaction_read_only=on`` and ``statement_timeout`` (R7.2, R7.4), and
``sslmode`` defaults to ``require`` (R7.20). ``configure`` sets each pooled
connection to read-only, non-autocommit mode (R7.3).

Import boundary B3: imports psycopg; lives under ``data/**``.
"""

from typing import TYPE_CHECKING

import psycopg
import psycopg.conninfo

if TYPE_CHECKING:
    from kognit_llm.config.secrets import DbCredentials
    from kognit_llm.config.settings import Settings

__all__ = ["build_conninfo", "configure"]


def build_conninfo(settings: "Settings", creds: "DbCredentials") -> str:
    """Build a conninfo string that is read-only from the first statement.

    The server-side ``options`` set ``default_transaction_read_only=on`` and the
    session ``statement_timeout`` so R7.2 and R7.4 hold without an extra round
    trip. ``connect_timeout`` is expressed in whole seconds as libpq requires.
    """
    statement_timeout_ms = settings.db_statement_timeout_ms
    connect_timeout_s = max(1, round(settings.db_connect_timeout_ms / 1000))
    server_options = (
        "-c default_transaction_read_only=on "
        f"-c statement_timeout={statement_timeout_ms}"
    )
    return psycopg.conninfo.make_conninfo(
        host=creds.host,
        port=creds.port,
        dbname=creds.dbname,
        user=creds.user,
        password=creds.password,
        sslmode=creds.sslmode,
        connect_timeout=connect_timeout_s,
        options=server_options,
    )


def configure(conn: psycopg.Connection) -> None:
    """Set a pooled connection read-only and non-autocommit (R7.3).

    psycopg emits ``BEGIN READ ONLY`` for a read-only connection, so an admitted
    statement runs inside a read-only transaction.
    """
    conn.read_only = True
    conn.autocommit = False
