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

    The ordered pipeline runs the token checks first, then parses the AST and runs
    the structural and allow-list/limit checks. First match wins, so the verdict
    and reason code are deterministic (R6.42). The verdict's ``statement_sha256``
    is computed over the exact original ``statement`` text (R6.45).
    """
    try:
        tokens = sql_ast.tokenize(statement)
    except sql_ast.SqlAstError:
        return _reject(statement, RejectionReason.UNPARSEABLE)

    token_reason = _check_tokens(statement, tokens, limits)
    if token_reason is not None:
        return _reject(statement, token_reason)

    # Normalize %s placeholders, then parse the AST.
    analysis_sql, placeholder_count = sql_ast.normalize_placeholders(statement)
    try:
        analysis = sql_ast.analyze(analysis_sql)
    except sql_ast.SqlAstError:
        return _reject(statement, RejectionReason.UNPARSEABLE)

    ast_reason = (
        _check_statement_shape(analysis)
        or _check_schema_and_objects(analysis, allowlist, approved_schema)
        or _check_functions(analysis, functions)
        or _check_limit_and_complexity(analysis, limits)
        or _check_parameterization(
            analysis, placeholder_count, len(params), user_message
        )
    )
    if ast_reason is not None:
        return _reject(statement, ast_reason)

    return _admit(statement)


def _check_tokens(
    statement: str, tokens: Sequence[sql_ast.SqlToken], limits: FirewallLimits
) -> RejectionReason | None:
    """Token-stream checks (1-4, 8); returns the first rejection reason or None."""
    meaningful = [t for t in tokens if t.token_type not in _COMMENT_TOKEN_NAMES]

    # Check 1: empty / whitespace-only / comments-only.
    if not meaningful or all(
        t.token_type in _SEPARATOR_TOKEN_NAMES for t in meaningful
    ):
        return RejectionReason.EMPTY_STATEMENT
    # Check 2: statement length.
    if len(statement) > limits.max_statement_chars:
        return RejectionReason.COMPLEXITY_EXCEEDED
    # Check 3: any comment token attached anywhere.
    if any(
        t.is_comment_carrier or t.token_type in _COMMENT_TOKEN_NAMES for t in tokens
    ):
        return RejectionReason.COMMENT_PRESENT
    # Check 4: any statement separator at any position.
    if any(t.token_type in _SEPARATOR_TOKEN_NAMES for t in tokens):
        return RejectionReason.SEPARATOR_PRESENT
    # Check 8: forbidden keyword token (non-literal tokens only).
    for tok in tokens:
        if tok.token_type in _LITERAL_TOKEN_NAMES:
            continue
        if tok.text.upper() in _FORBIDDEN_KEYWORDS:
            return RejectionReason.FORBIDDEN_KEYWORD
    return None


def _check_statement_shape(analysis: "sql_ast.Analysis") -> RejectionReason | None:
    """Structural AST checks (6-7, 9-12); returns the first reason or None."""
    if analysis.statement_count != 1:
        return RejectionReason.MULTIPLE_STATEMENTS
    if not analysis.select_rooted:
        return RejectionReason.NOT_SELECT
    if analysis.data_modifying_cte:
        return RejectionReason.DATA_MODIFYING_CTE
    if analysis.nested_dml:
        return RejectionReason.NESTED_DML
    if analysis.select_into:
        return RejectionReason.SELECT_INTO
    if analysis.locking_clause:
        return RejectionReason.LOCKING_CLAUSE
    return None


def _check_schema_and_objects(
    analysis: "sql_ast.Analysis", allowlist: AllowList, approved_schema: str
) -> RejectionReason | None:
    """Schema/table/column allow-list checks (13-16); first reason or None."""
    for table in analysis.tables:
        if (
            table.schema in {"pg_catalog", "information_schema"}
            or table.name.startswith("pg_")
        ):
            return RejectionReason.SYSTEM_CATALOG_REFERENCE
    for table in analysis.tables:
        if table.schema and table.schema != approved_schema:
            return RejectionReason.UNAPPROVED_SCHEMA
    table_names = [t.name for t in analysis.tables]
    for name in table_names:
        if not allowlist.has_table(name):
            return RejectionReason.UNAPPROVED_TABLE
    for column in analysis.columns:
        if column.name == "*":
            continue
        if column.table:
            if not allowlist.has_column(column.table, column.name):
                return RejectionReason.UNAPPROVED_COLUMN
        elif allowlist.resolve_unqualified(column.name, table_names) is None:
            return RejectionReason.UNAPPROVED_COLUMN
    return None


def _check_functions(
    analysis: "sql_ast.Analysis", functions: frozenset[str]
) -> RejectionReason | None:
    """Function checks (17-18); first reason or None."""
    for func in analysis.function_names:
        if func in _FORBIDDEN_FUNCTIONS:
            return RejectionReason.FORBIDDEN_FUNCTION
    approved = {f.lower() for f in functions}
    for func in analysis.function_names:
        if func not in approved:
            return RejectionReason.UNAPPROVED_FUNCTION
    return None


def _check_limit_and_complexity(
    analysis: "sql_ast.Analysis", limits: FirewallLimits
) -> RejectionReason | None:
    """LIMIT/OFFSET/join/complexity checks (19-24); first reason or None."""
    if not analysis.limit.present:
        return RejectionReason.MISSING_LIMIT
    if not analysis.limit.is_integer_literal or (
        analysis.limit.value is not None and analysis.limit.value < 0
    ):
        return RejectionReason.NON_LITERAL_LIMIT
    if analysis.limit.value is not None and analysis.limit.value > limits.row_cap:
        return RejectionReason.LIMIT_EXCEEDS_ROW_CAP
    if analysis.offset_non_literal:
        return RejectionReason.NON_LITERAL_OFFSET
    if analysis.join_without_predicate:
        return RejectionReason.MISSING_JOIN_PREDICATE
    if (
        analysis.join_count > limits.max_join_count
        or analysis.subquery_depth > limits.max_subquery_depth
        or analysis.set_operation_arms > limits.max_set_operation_arms
    ):
        return RejectionReason.COMPLEXITY_EXCEEDED
    return None


def _check_parameterization(
    analysis: "sql_ast.Analysis",
    placeholder_count: int,
    param_count: int,
    user_message: str,
) -> RejectionReason | None:
    """Parameterization check (25); first reason or None."""
    if placeholder_count != param_count:
        return RejectionReason.UNPARAMETERIZED_LITERAL
    for literal in analysis.inline_string_literals:
        if literal and literal in user_message:
            return RejectionReason.UNPARAMETERIZED_LITERAL
    return None
