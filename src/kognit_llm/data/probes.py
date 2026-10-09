"""Warehouse liveness, privilege and schema-verification probes (R7.10, R7.16-R7.18).

Each probe uses the pool and the static internal queries, never raises, and never
echoes a connection detail (R7.10, R16.25). ``probe_warehouse`` performs a
liveness check; ``probe_privileges`` runs the write-privilege verification of Q3
and reports a failure naming only the privilege category found (R7.17). The
results feed ``health.py``.

Import boundary B3: imports psycopg_pool; lives under ``data/**``.
"""

from dataclasses import dataclass, field
from typing import Literal

from psycopg_pool import ConnectionPool

from kognit_llm.schema.internal_queries import (
    Q1_LIVENESS,
    Q3_PRIVILEGE_VERIFICATION,
)

__all__ = ["WarehouseStatus", "probe_privileges", "probe_warehouse"]

# The seven write privileges Q3 reports, in column order.
_WRITE_PRIVILEGES = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "CREATE",
)


@dataclass(frozen=True, slots=True)
class WarehouseStatus:
    """A warehouse probe outcome, carrying no connection detail (R7.10)."""

    status: Literal["ok", "failed"]
    detail: str = ""
    write_privileges_found: tuple[str, ...] = field(default_factory=tuple)


def probe_warehouse(pool: ConnectionPool) -> WarehouseStatus:
    """Check warehouse liveness with Q1, never raising (R7.10, R16.25)."""
    try:
        pool.open()  # idempotent lazy-open; the pool is built with open=False
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(Q1_LIVENESS)
            cur.fetchone()
        return WarehouseStatus(status="ok")
    except Exception:
        # No connection detail is surfaced (R7.34); health reports "failed".
        return WarehouseStatus(status="failed", detail="warehouse unreachable")


def probe_privileges(
    pool: ConnectionPool, approved_schema: str, relations: tuple[str, ...]
) -> WarehouseStatus:
    """Verify the connected role holds no write privilege (R7.16-R7.17).

    Returns ``failed`` naming the write-privilege categories found, or when the
    check cannot complete (R7.18). Names only the privilege category, never a
    connection detail.
    """
    try:
        pool.open()  # idempotent lazy-open; the pool is built with open=False
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                Q3_PRIVILEGE_VERIFICATION, (approved_schema, list(relations))
            )
            row = cur.fetchone()
        if row is None:
            return WarehouseStatus(
                status="failed", detail="privilege verification returned no row"
            )
        found = tuple(
            privilege
            for privilege, held in zip(_WRITE_PRIVILEGES, row, strict=True)
            if held
        )
        if found:
            return WarehouseStatus(
                status="failed",
                detail="write privilege found",
                write_privileges_found=found,
            )
        return WarehouseStatus(status="ok")
    except Exception:
        return WarehouseStatus(
            status="failed", detail="privilege verification unavailable"
        )
