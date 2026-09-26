"""Approved schema allow-list loader (R4.1-R4.2, R4.13, R4.16, R4.19-R4.22).

Loads the ``allowlist.yaml`` artifact into a validated, immutable ``AllowList``
carrying the version identifier. Columns are scoped per table (R4.19), so a name
allow-listed for one table is not allow-listed for another. ``resolve_unqualified``
implements R4.21-R4.22: exactly one owning table resolves; more than one owner is
ambiguous and yields ``None`` so the firewall rejects it.

Each table carries a verification state (R4.15-R4.18): ``verified`` (confirmed
present in the warehouse), ``absent`` (confirmed missing — removed from context
and rejected by the firewall) or ``unverified`` (enforced as declared, reported
on ``GET /health``). Loading yields ``unverified``; the schema subsystem promotes
to ``verified``/``absent`` lazily on first warehouse use (M-5/M-9).
"""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ALLOWLIST_RESOURCE", "AllowList", "TableEntry", "load_allowlist"]

ALLOWLIST_RESOURCE = "allowlist.yaml"


class TableEntry(BaseModel):
    """One allow-listed relation: its kind, columns, measures and enumerables."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["fact", "dimension", "bridge"]
    columns: frozenset[str]
    measures: frozenset[str] = frozenset()
    # YAML key is ``enumerate``; the attribute avoids shadowing the builtin.
    enumerate_attributes: frozenset[str] = Field(
        default=frozenset(), alias="enumerate"
    )
    verification: Literal["verified", "absent", "unverified"] = "unverified"


class AllowList(BaseModel):
    """The whole approved schema allow-list, keyed by physical table name."""

    model_config = ConfigDict(frozen=True)

    version: str
    approved_schema: str
    tables: Mapping[str, TableEntry]
    functions: frozenset[str]

    def has_table(self, name: str) -> bool:
        """True when ``name`` is allow-listed and not marked ``absent`` (R4.16)."""
        entry = self.tables.get(name)
        return entry is not None and entry.verification != "absent"

    def has_column(self, table: str, column: str) -> bool:
        """True when ``column`` is allow-listed for ``table`` (R4.11, R4.19)."""
        entry = self.tables.get(table)
        if entry is None or entry.verification == "absent":
            return False
        return column in entry.columns or column in entry.measures

    def resolve_unqualified(
        self, column: str, candidate_tables: Sequence[str]
    ) -> str | None:
        """Resolve an unqualified column to its single owning table.

        Returns that table when exactly one candidate allow-lists the column;
        returns ``None`` when zero or more than one candidate owns it, so the
        firewall rejects the ambiguous or unknown reference (R4.21-R4.22).
        """
        owners = [t for t in candidate_tables if self.has_column(t, column)]
        return owners[0] if len(owners) == 1 else None


def _load_from_text(text: str) -> AllowList:
    raw = yaml.safe_load(text)
    tables = {
        name: TableEntry.model_validate(entry)
        for name, entry in raw["tables"].items()
    }
    return AllowList(
        version=raw["version"],
        approved_schema=raw["approved_schema"],
        tables=tables,
        functions=frozenset(raw["functions"]),
    )


@lru_cache(maxsize=1)
def load_allowlist() -> AllowList:
    """Load and cache the packaged allow-list artifact (R4.13)."""
    text = (
        resources.files("kognit_llm.schema")
        .joinpath(ALLOWLIST_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return _load_from_text(text)
