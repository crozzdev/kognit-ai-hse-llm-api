"""Read-only warehouse executor (R6.43-R6.46, R7.6-R7.7, R7.12-R7.13, R7.31-R7.33).

``WarehouseExecutor.execute_admitted`` is the only entry point that accepts a
caller-supplied SQL string, and it does so only with an accompanying ``ADMIT``
verdict whose ``statement_sha256`` matches a freshly recomputed hash of the exact
statement text (R6.45). It opens a read-only transaction, applies the row, column
and byte caps, records durations, and translates every driver exception through
``data/errors`` so no connection detail leaks (R7.34).

Import boundary B3/B5: imports psycopg; the only module that executes admitted
SQL.
"""

import hashlib
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, LiteralString, cast

from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict

from kognit_llm.data.errors import translate
from kognit_llm.data.probes import WarehouseStatus, probe_warehouse

if TYPE_CHECKING:
    from kognit_llm.safety.firewall import FirewallVerdict

__all__ = ["BoundParam", "ResultSet", "WarehouseExecutor"]

BoundParam = str | int | float | bool | None


class ResultSet(BaseModel):
    """A capped, read-only warehouse result (R7.7, R7.13, R7.32)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    truncated: bool
    duration_ms: int


class ExecutionRefused(Exception):
    """Raised when a statement's hash or verdict does not authorize execution."""


class WarehouseExecutor:
    """Executes only firewall-admitted statements against the read-only pool."""

    def __init__(
        self,
        pool: ConnectionPool,
        *,
        row_cap: int,
        max_result_columns: int,
        max_result_bytes: int,
    ) -> None:
        self._pool = pool
        self._row_cap = row_cap
        self._max_result_columns = max_result_columns
        self._max_result_bytes = max_result_bytes

    def execute_admitted(
        self,
        statement: str,
        params: Sequence[BoundParam],
        verdict: "FirewallVerdict",
    ) -> ResultSet:
        """Execute ``statement`` only if ``verdict`` admits this exact text (R6.45).

        Refuses unless ``verdict.verdict == "ADMIT"`` and the recomputed
        ``sha256(statement)`` equals ``verdict.statement_sha256`` (R6.45, R7.35).
        Fetches ``row_cap + 1`` rows to detect truncation (R7.7), then applies the
        column and byte caps (R7.32-R7.33). Driver exceptions are translated so no
        connection detail leaks (R7.34).
        """
        if verdict.verdict != "ADMIT":
            raise ExecutionRefused("statement is not admitted")
        if hashlib.sha256(statement.encode("utf-8")).hexdigest() != (
            verdict.statement_sha256
        ):
            raise ExecutionRefused("statement text does not match the admitted hash")

        started = time.monotonic()
        try:
            # Lazy-open on first use: the pool is built with open=False so importing
            # performs no connection (R16.21-R16.22); open() is idempotent, so this
            # opens it once per execution environment and is a no-op thereafter.
            self._pool.open()
            with self._pool.connection() as conn, conn.transaction():
                with conn.cursor() as cur:
                    # The statement is firewall-validated and hash-bound above,
                    # so it is safe to pass to psycopg's LiteralString-typed API.
                    cur.execute(cast(LiteralString, statement), list(params))
                    raw_columns = (
                        tuple(desc.name for desc in cur.description)
                        if cur.description is not None
                        else ()
                    )
                    fetched = cur.fetchmany(self._row_cap + 1)
        except Exception as exc:  # translated; original never surfaced (R7.34)
            raise translate(exc) from None

        duration_ms = int((time.monotonic() - started) * 1000)
        return self._build_result(raw_columns, fetched, duration_ms)

    def probe(self) -> WarehouseStatus:
        """Report warehouse liveness without raising (R7.10)."""
        return probe_warehouse(self._pool)

    def _build_result(
        self,
        columns: tuple[str, ...],
        fetched: list[tuple[object, ...]],
        duration_ms: int,
    ) -> ResultSet:
        # Row cap: keep at most row_cap rows; a surplus row marks truncation (R7.7).
        truncated = len(fetched) > self._row_cap
        rows = [tuple(row) for row in fetched[: self._row_cap]]

        # Column cap (R7.32-R7.33).
        if len(columns) > self._max_result_columns:
            truncated = True
            keep = self._max_result_columns
            columns = columns[:keep]
            rows = [row[:keep] for row in rows]

        # Byte cap: drop trailing rows until the estimated size fits (R7.32-R7.33).
        rows, byte_truncated = self._apply_byte_cap(rows)
        truncated = truncated or byte_truncated

        return ResultSet(
            columns=columns,
            rows=tuple(rows),
            truncated=truncated,
            duration_ms=duration_ms,
        )

    def _apply_byte_cap(
        self, rows: list[tuple[object, ...]]
    ) -> tuple[list[tuple[object, ...]], bool]:
        kept: list[tuple[object, ...]] = []
        total = 0
        for row in rows:
            size = sum(len(str(value).encode("utf-8")) for value in row)
            if total + size > self._max_result_bytes and kept:
                return kept, True
            kept.append(row)
            total += size
        return kept, len(kept) < len(rows)
