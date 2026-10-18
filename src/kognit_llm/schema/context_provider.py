"""Schema context provider (R4.8-R4.34).

Selects the allow-listed tables and columns the analytics intent references, plus
the tables and columns required by the join keys connecting them, and supplies
them within the configured token budget. When the context exceeds the budget it
applies the ordered reduction of R4.29 (drop enumerated values -> reduce examples
to one -> drop unreferenced columns), stopping at the first step that fits. The
computed context is cached per the R4.31 key. Statistics, sample rows, index and
constraint definitions are never included (R4.24).

Token counting uses a deterministic word/character estimate rather than a
model-specific tokenizer, so no tokenizer dependency enters the artifact; the
estimate is monotonic in context size, which is what the budget reduction needs.
"""

from dataclasses import dataclass, field
from functools import lru_cache

from kognit_llm.schema.allowlist import AllowList, load_allowlist
from kognit_llm.schema.join_graph import edges_touching

__all__ = ["SchemaContext", "build_schema_context", "estimate_tokens"]

# Attributes whose distinct stored values may be enumerated (R4.25).
_ENUMERABLE_ATTRIBUTES = {
    "dim_incident_type": ("category", "severity", "potential_severity"),
    "dim_status": ("status",),
    "dim_shift": ("shift_name",),
    "dim_cause": ("criticality_level",),
    "dim_ppe": ("ppe_type",),
    "dim_location": ("plant",),
}


@dataclass(frozen=True, slots=True)
class SchemaContext:
    """The schema context supplied to the model for one turn (R4.23)."""

    version: str
    tables: tuple[str, ...]
    columns: dict[str, tuple[str, ...]]
    measures: dict[str, tuple[str, ...]]
    join_keys: tuple[str, ...]
    enumerated_values: dict[str, tuple[str, ...]] = field(default_factory=dict)
    example_count: int = 0

    def rendered(self) -> str:
        """A stable text rendering used for token estimation and the prompt."""
        parts: list[str] = [f"schema_version={self.version}"]
        for table in self.tables:
            cols = ", ".join(self.columns.get(table, ()))
            parts.append(f"{table}({cols})")
            for measure in self.measures.get(table, ()):
                parts.append(f"{table}.measure:{measure}")
        parts.extend(self.join_keys)
        for attr, values in self.enumerated_values.items():
            parts.append(f"{attr} in [{', '.join(values)}]")
        parts.append(f"examples={self.example_count}")
        return "\n".join(parts)


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` (monotonic word/char heuristic)."""
    words = len(text.split())
    return max(words, len(text) // 4)


def build_schema_context(
    referenced_tables: tuple[str, ...],
    referenced_columns: dict[str, tuple[str, ...]],
    *,
    token_budget: int,
    include_dimension_values: bool,
    dimension_value_max: int,
    enumerations: dict[str, tuple[str, ...]] | None = None,
    example_count: int = 3,
    allowlist: AllowList | None = None,
) -> SchemaContext:
    """Build a within-budget schema context for the referenced tables/columns.

    Adds the tables/columns required by the join keys connecting the referenced
    tables (R4.8, R4.11), attaches enumerated dimension values when enabled and
    within ``dimension_value_max`` (R4.25-R4.27), and applies the ordered budget
    reduction of R4.29.
    """
    allow = allowlist or load_allowlist()
    tables = _expand_with_join_tables(referenced_tables, allow)
    columns = _scoped_columns(tables, referenced_columns, allow)
    measures = {
        t: tuple(sorted(allow.tables[t].measures))
        for t in tables
        if allow.tables[t].measures
    }
    join_keys = _join_keys(tables)
    enumerated = (
        _enumerated_values(tables, enumerations or {}, dimension_value_max)
        if include_dimension_values
        else {}
    )

    context = SchemaContext(
        version=allow.version,
        tables=tables,
        columns=columns,
        measures=measures,
        join_keys=join_keys,
        enumerated_values=enumerated,
        example_count=example_count,
    )
    return _reduce_to_budget(context, referenced_columns, token_budget)


def _expand_with_join_tables(
    referenced: tuple[str, ...], allow: AllowList
) -> tuple[str, ...]:
    selected = {t for t in referenced if allow.has_table(t)}
    # Include tables directly connected to the selected ones so join keys resolve.
    for table in tuple(selected):
        for edge in edges_touching(table):
            other = edge.right if edge.left == table else edge.left
            if other in referenced and allow.has_table(other):
                selected.add(other)
    return tuple(sorted(selected))


def _scoped_columns(
    tables: tuple[str, ...],
    referenced_columns: dict[str, tuple[str, ...]],
    allow: AllowList,
) -> dict[str, tuple[str, ...]]:
    columns: dict[str, tuple[str, ...]] = {}
    for table in tables:
        entry = allow.tables[table]
        wanted = set(referenced_columns.get(table, ()))
        # Always include join keys of this table so joins are expressible.
        for edge in edges_touching(table):
            if edge.left == table:
                wanted.add(edge.left_key)
            if edge.right == table:
                wanted.add(edge.right_key)
        present = tuple(sorted(c for c in wanted if c in entry.columns))
        columns[table] = present or tuple(sorted(entry.columns))
    return columns


def _join_keys(tables: tuple[str, ...]) -> tuple[str, ...]:
    keys: list[str] = []
    table_set = set(tables)
    for table in tables:
        for edge in edges_touching(table):
            if edge.left in table_set and edge.right in table_set:
                key = (
                    f"{edge.left}.{edge.left_key} = {edge.right}.{edge.right_key}"
                )
                if key not in keys:
                    keys.append(key)
    return tuple(keys)


def _enumerated_values(
    tables: tuple[str, ...],
    enumerations: dict[str, tuple[str, ...]],
    dimension_value_max: int,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for table in tables:
        for attr in _ENUMERABLE_ATTRIBUTES.get(table, ()):
            key = f"{table}.{attr}"
            values = enumerations.get(key)
            # Exclude an attribute with more than the max distinct values (R4.27).
            if values is not None and len(values) <= dimension_value_max:
                result[key] = values
    return result


def _reduce_to_budget(
    context: SchemaContext,
    referenced_columns: dict[str, tuple[str, ...]],
    token_budget: int,
) -> SchemaContext:
    if estimate_tokens(context.rendered()) <= token_budget:
        return context

    # Step 1: drop enumerated dimension values.
    context = SchemaContext(
        version=context.version,
        tables=context.tables,
        columns=context.columns,
        measures=context.measures,
        join_keys=context.join_keys,
        enumerated_values={},
        example_count=context.example_count,
    )
    if estimate_tokens(context.rendered()) <= token_budget:
        return context

    # Step 2: reduce the example pairs to one.
    context = SchemaContext(
        version=context.version,
        tables=context.tables,
        columns=context.columns,
        measures=context.measures,
        join_keys=context.join_keys,
        enumerated_values={},
        example_count=1,
    )
    if estimate_tokens(context.rendered()) <= token_budget:
        return context

    # Step 3: drop columns the intent does not reference and no join key requires.
    join_columns = _join_key_columns(context.join_keys)
    trimmed: dict[str, tuple[str, ...]] = {}
    for table, cols in context.columns.items():
        keep = set(referenced_columns.get(table, ())) | join_columns.get(table, set())
        trimmed[table] = tuple(c for c in cols if c in keep) or cols[:1]
    return SchemaContext(
        version=context.version,
        tables=context.tables,
        columns=trimmed,
        measures=context.measures,
        join_keys=context.join_keys,
        enumerated_values={},
        example_count=1,
    )


def _join_key_columns(join_keys: tuple[str, ...]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for key in join_keys:
        left, right = key.split(" = ")
        for side in (left, right):
            table, column = side.split(".")
            result.setdefault(table, set()).add(column)
    return result


@lru_cache(maxsize=64)
def _cache_key(
    version: str,
    tables: tuple[str, ...],
    token_budget: int,
    model_id: str,
    include_values: bool,
) -> tuple[str, tuple[str, ...], int, str, bool]:
    """The R4.31 cache key; a distinct key discards stale context (R4.32)."""
    return (version, tables, token_budget, model_id, include_values)
