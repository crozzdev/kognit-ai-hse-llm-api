"""Deny-by-default SQL query firewall (R6, R13.5, R16.33).

``validate_sql`` is an ordered pipeline of predicate checks over a token stream
and an AST, both produced once by ``safety/sql_ast.py``. First match wins, which
makes the verdict and the reason code deterministic (R6.42). A statement is
admitted only when every check passes (R6.19). The verdict is bound to the exact
original statement text by sha256 so nothing downstream can substitute a
different statement (R6.45).

Import boundary: this module imports only ``safety/sql_ast.py``, ``hashlib`` and
project types. It issues no model-provider call and no network call (R6.2, B1).
"""

import hashlib
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from kognit_llm.safety import sql_ast
from kognit_llm.safety.reason_codes import RejectionReason
from kognit_llm.schema.allowlist import AllowList

__all__ = ["FirewallLimits", "FirewallVerdict", "validate_sql"]

BoundParam = str | int | float | bool | None

# The 40 forbidden keyword names of R6.7, matched case-insensitively against
# keyword tokens only, never inside string literals or quoted identifiers.
_FORBIDDEN_KEYWORDS = frozenset(
    {
        "DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "CREATE",
        "GRANT", "REVOKE", "COPY", "MERGE", "REPLACE", "VACUUM", "CALL", "DO",
        "EXECUTE", "SET", "RESET", "LOCK", "COMMENT", "REINDEX", "REFRESH",
        "NOTIFY", "LISTEN", "PREPARE", "DECLARE", "FETCH", "MOVE", "CLOSE",
        "SECURITY", "ROLE", "USER", "DATABASE", "SCHEMA", "TABLESPACE",
        "EXTENSION", "FUNCTION",
    }
)

# Forbidden functions of R6.30 plus the administrative/file/config families.
_FORBIDDEN_FUNCTIONS = frozenset(
    {
        "current_setting", "set_config", "pg_read_file", "pg_read_binary_file",
        "pg_stat_file", "pg_ls_dir", "lo_import", "lo_export", "dblink",
        "dblink_connect", "pg_sleep", "query_to_xml",
    }
)

# Token-type names whose text is excluded from keyword matching (R6.22).
_LITERAL_TOKEN_NAMES = frozenset(
    {"STRING", "NATIONAL_STRING", "RAW_STRING", "HEREDOC_STRING", "IDENTIFIER"}
)

_COMMENT_TOKEN_NAMES = frozenset({"COMMENT"})
_SEPARATOR_TOKEN_NAMES = frozenset({"SEMICOLON"})


class FirewallLimits(BaseModel):
    """Configurable numeric bounds the firewall enforces."""

    model_config = ConfigDict(frozen=True)

    row_cap: int
    max_statement_chars: int
    max_join_count: int
    max_subquery_depth: int
    max_set_operation_arms: int


class FirewallVerdict(BaseModel):
    """The firewall's decision, bound to the exact statement text (R6.45)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Literal["ADMIT", "REJECT"]
    statement_sha256: str
    reason: RejectionReason | None = None


def _sha256(statement: str) -> str:
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _reject(statement: str, reason: RejectionReason) -> FirewallVerdict:
    return FirewallVerdict(
        verdict="REJECT", statement_sha256=_sha256(statement), reason=reason
    )


def _admit(statement: str) -> FirewallVerdict:
    return FirewallVerdict(verdict="ADMIT", statement_sha256=_sha256(statement))


def validate_sql(
    statement: str,
    params: Sequence[BoundParam],
    *,
    allowlist: AllowList,
    functions: frozenset[str],
    limits: FirewallLimits,
    approved_schema: str,
    user_message: str,
) -> FirewallVerdict:
    """Return an ``ADMIT`` or ``REJECT`` verdict for ``statement`` (R6.19).

    The verdict's ``statement_sha256`` is computed over the exact original
    ``statement`` text, so the executor can refuse any substituted text (R6.45).
    """
    # ── Token-based checks (1-4, 8) ──────────────────────────────────────────
    try:
        tokens = sql_ast.tokenize(statement)
    except sql_ast.SqlAstError:
        return _reject(statement, RejectionReason.UNPARSEABLE)

    meaningful = [t for t in tokens if t.token_type not in _COMMENT_TOKEN_NAMES]

    # Check 1: empty / whitespace-only / comments-only.
    if not meaningful or all(
        t.token_type in _SEPARATOR_TOKEN_NAMES for t in meaningful
    ):
        return _reject(statement, RejectionReason.EMPTY_STATEMENT)

    # Check 2: statement length.
    if len(statement) > limits.max_statement_chars:
        return _reject(statement, RejectionReason.COMPLEXITY_EXCEEDED)

    # Check 3: any comment token attached anywhere.
    if any(
        t.is_comment_carrier or t.token_type in _COMMENT_TOKEN_NAMES for t in tokens
    ):
        return _reject(statement, RejectionReason.COMMENT_PRESENT)

    # Check 4: any statement separator at any position.
    if any(t.token_type in _SEPARATOR_TOKEN_NAMES for t in tokens):
        return _reject(statement, RejectionReason.SEPARATOR_PRESENT)

    # Check 8: forbidden keyword token (text match on non-literal tokens only).
    for tok in tokens:
        if tok.token_type in _LITERAL_TOKEN_NAMES:
            continue
        if tok.text.upper() in _FORBIDDEN_KEYWORDS:
            return _reject(statement, RejectionReason.FORBIDDEN_KEYWORD)

    # ── AST-based checks (5-7, 9-25) ─────────────────────────────────────────
    # Check 5: tokenize + parse succeed. Normalize %s placeholders first.
    analysis_sql, placeholder_count = sql_ast.normalize_placeholders(statement)
    try:
        analysis = sql_ast.analyze(analysis_sql)
    except sql_ast.SqlAstError:
        return _reject(statement, RejectionReason.UNPARSEABLE)

    # Check 6: exactly one top-level statement.
    if analysis.statement_count != 1:
        return _reject(statement, RejectionReason.MULTIPLE_STATEMENTS)

    # Check 7: SELECT / set-operation / WITH-of-SELECTs root.
    if not analysis.select_rooted:
        return _reject(statement, RejectionReason.NOT_SELECT)

    # Check 9: data-modifying CTE.
    if analysis.data_modifying_cte:
        return _reject(statement, RejectionReason.DATA_MODIFYING_CTE)

    # Check 10: nested DML anywhere.
    if analysis.nested_dml:
        return _reject(statement, RejectionReason.NESTED_DML)

    # Check 11: SELECT ... INTO.
    if analysis.select_into:
        return _reject(statement, RejectionReason.SELECT_INTO)

    # Check 12: row-locking clause.
    if analysis.locking_clause:
        return _reject(statement, RejectionReason.LOCKING_CLAUSE)

    # Check 13: system-catalog reference.
    for table in analysis.tables:
        if (
            table.schema in {"pg_catalog", "information_schema"}
            or table.name.startswith("pg_")
        ):
            return _reject(statement, RejectionReason.SYSTEM_CATALOG_REFERENCE)

    # Check 14: every qualified schema equals the approved schema.
    for table in analysis.tables:
        if table.schema and table.schema != approved_schema:
            return _reject(statement, RejectionReason.UNAPPROVED_SCHEMA)

    # Check 15: every table identifier is allow-listed and not absent.
    table_names = [t.name for t in analysis.tables]
    for name in table_names:
        if not allowlist.has_table(name):
            return _reject(statement, RejectionReason.UNAPPROVED_TABLE)

    # Check 16: every column resolves to exactly one allow-listed owner.
    for column in analysis.columns:
        if column.name == "*":
            continue
        if column.table:
            if not allowlist.has_column(column.table, column.name):
                return _reject(statement, RejectionReason.UNAPPROVED_COLUMN)
        elif allowlist.resolve_unqualified(column.name, table_names) is None:
            return _reject(statement, RejectionReason.UNAPPROVED_COLUMN)

    # Check 17: forbidden function.
    for func in analysis.function_names:
        if func in _FORBIDDEN_FUNCTIONS:
            return _reject(statement, RejectionReason.FORBIDDEN_FUNCTION)

    # Check 18: every remaining function is in the approved set.
    approved = {f.lower() for f in functions}
    for func in analysis.function_names:
        if func not in approved:
            return _reject(statement, RejectionReason.UNAPPROVED_FUNCTION)

    # Check 19: LIMIT present on the outermost query.
    if not analysis.limit.present:
        return _reject(statement, RejectionReason.MISSING_LIMIT)

    # Check 20: LIMIT is a single non-negative integer literal.
    if not analysis.limit.is_integer_literal or (
        analysis.limit.value is not None and analysis.limit.value < 0
    ):
        return _reject(statement, RejectionReason.NON_LITERAL_LIMIT)

    # Check 21: LIMIT value within the row cap.
    if analysis.limit.value is not None and analysis.limit.value > limits.row_cap:
        return _reject(statement, RejectionReason.LIMIT_EXCEEDS_ROW_CAP)

    # Check 22: OFFSET, when present, is a non-negative integer literal.
    if analysis.offset_non_literal:
        return _reject(statement, RejectionReason.NON_LITERAL_OFFSET)

    # Check 23: every join has a predicate.
    if analysis.join_without_predicate:
        return _reject(statement, RejectionReason.MISSING_JOIN_PREDICATE)

    # Check 24: complexity bounds.
    if (
        analysis.join_count > limits.max_join_count
        or analysis.subquery_depth > limits.max_subquery_depth
        or analysis.set_operation_arms > limits.max_set_operation_arms
    ):
        return _reject(statement, RejectionReason.COMPLEXITY_EXCEEDED)

    # Check 25: parameterization — placeholder count matches, no inline literal
    # equals a substring of the user message, every user value is a placeholder.
    if placeholder_count != len(params):
        return _reject(statement, RejectionReason.UNPARAMETERIZED_LITERAL)
    for literal in analysis.inline_string_literals:
        if literal and literal in user_message:
            return _reject(statement, RejectionReason.UNPARAMETERIZED_LITERAL)

    return _admit(statement)
