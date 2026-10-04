"""Warehouse exception taxonomy (R7.19, R7.21, R7.27-R7.30, R7.34).

``translate`` maps a psycopg driver exception to one of the HTTP-facing
``WarehouseError`` subclasses of ``api/errors.py``. No translated exception
carries the host, port, database name, role name, password or connection string
(R7.34): only the fixed per-category user message survives.

Import boundary B3: this module and the rest of ``data/**`` (plus
``config/secrets.py``) are the only places permitted to import ``psycopg``.
"""

import psycopg

from kognit_llm.api.errors import (
    WarehouseError,
    WarehousePrivilegeDenied,
    WarehouseStatementTimeout,
    WarehouseUnavailable,
    WarehouseUndefinedObject,
    WarehouseWriteRejected,
)

__all__ = ["translate"]


def translate(exc: Exception) -> WarehouseError:
    """Return the taxonomy error for a psycopg driver exception (R7.34).

    Classification order is specific-before-general. Any exception whose class is
    not recognized is treated as a connection-class failure
    (``WarehouseUnavailable``), which fails closed with HTTP 503. The original
    exception is intentionally not chained into the message, so no connection
    detail can leak through ``str(err)``.
    """
    # Statement timeout / cancellation (R7.6, R7.31).
    if isinstance(exc, psycopg.errors.QueryCanceled):
        return WarehouseStatementTimeout()

    # Read-only transaction violation surfaced by the warehouse (R7.19).
    if isinstance(exc, psycopg.errors.ReadOnlySqlTransaction):
        return WarehouseWriteRejected()

    # Insufficient privilege on a referenced object; object name withheld (R7.29).
    if isinstance(exc, psycopg.errors.InsufficientPrivilege):
        return WarehousePrivilegeDenied()

    # Undefined table/column/object; identifier withheld (R7.30).
    if isinstance(
        exc,
        (
            psycopg.errors.UndefinedTable,
            psycopg.errors.UndefinedColumn,
            psycopg.errors.UndefinedObject,
            psycopg.errors.UndefinedFunction,
        ),
    ):
        return WarehouseUndefinedObject()

    # Connect, TLS, authentication and pool-acquisition failures (R7.21, R7.27-R7.28).
    return WarehouseUnavailable()
