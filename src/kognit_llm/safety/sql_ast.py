"""SQL tokenizer/parser adapter over sqlglot (R6.20-R6.21, R6.25-R6.26, R16.33).

The firewall reaches the parser only through this module, which exposes
``tokenize`` and ``parse`` in project-owned types (``SqlToken``, ``SqlTree``). If
sqlglot ever proves unable to classify a construct, only this module is
reimplemented; no firewall rule changes.

Placeholder normalization: psycopg ``%s`` markers are not valid SQL to a parser,
so ``normalize_placeholders`` rewrites each ``%s`` that lies outside a string
literal, dollar-quoted literal or quoted identifier into a named placeholder
``:p{n}`` on an **analysis copy**. Positions come from the token stream, never
from substring scanning (R6.21). The firewall binds its verdict to the original
text by sha256, so this analysis copy never reaches the warehouse (R6.45).

Import boundary B1: this module imports no provider client, no database driver
and opens no network connection.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError, TokenError
from sqlglot.tokens import Token, TokenType

__all__ = [
    "Analysis",
    "SqlAstError",
    "SqlToken",
    "analyze",
    "normalize_placeholders",
    "tokenize",
]

_DIALECT = "postgres"

# DML expression types detected at any depth (R6.25-R6.26).
DML_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
)

# Token types whose text must be excluded from keyword matching (R6.22): string
# literals, dollar-quoted strings and quoted identifiers.
_LITERAL_TOKEN_TYPES = frozenset(
    {
        TokenType.STRING,
        TokenType.NATIONAL_STRING,
        TokenType.RAW_STRING,
        TokenType.HEREDOC_STRING,
        TokenType.IDENTIFIER,  # double-quoted identifier
    }
)


class SqlAstError(Exception):
    """Raised when the SQL cannot be tokenized or parsed (yields UNPARSEABLE)."""


@dataclass(frozen=True, slots=True)
class SqlToken:
    """A project-owned classified token."""

    token_type: str
    text: str
    start: int
    end: int
    is_comment_carrier: bool


@dataclass(frozen=True, slots=True)
class SqlTree:
    """A project-owned wrapper over the parsed statement list."""

    statements: tuple[exp.Expression, ...]

    @property
    def root(self) -> exp.Expression:
        """The single top-level statement (callers check count first)."""
        return self.statements[0]


def tokenize(sql: str) -> list[SqlToken]:
    """Tokenize ``sql`` in the PostgreSQL dialect (R6.21).

    A token carries any comments that the tokenizer attached to it, so a comment
    anywhere in the statement is detectable via ``is_comment_carrier`` (R6.8).
    """
    try:
        raw: list[Token] = sqlglot.tokenize(sql, read=_DIALECT)
    except TokenError as err:
        raise SqlAstError(str(err)) from err
    return [
        SqlToken(
            token_type=tok.token_type.name,
            text=tok.text,
            start=tok.start,
            end=tok.end,
            is_comment_carrier=bool(tok.comments),
        )
        for tok in raw
    ]


def parse(sql: str) -> SqlTree:
    """Parse ``sql`` into a ``SqlTree`` of one or more statements (R6.20).

    Raises ``SqlAstError`` on any tokenizer or parser failure so the firewall can
    fail closed with ``UNPARSEABLE``.
    """
    try:
        parsed = sqlglot.parse(sql, read=_DIALECT)
    except SqlglotError as err:
        raise SqlAstError(str(err)) from err
    statements: tuple[exp.Expression, ...] = tuple(
        stmt for stmt in parsed if isinstance(stmt, exp.Expression)
    )
    if not statements:
        raise SqlAstError("no parseable statement")
    return SqlTree(statements=statements)


def normalize_placeholders(sql: str) -> tuple[str, int]:
    """Return an analysis copy with ``%s`` markers turned into ``:p{n}``.

    Only ``%s`` occurrences outside string literals, dollar-quoted literals and
    quoted identifiers are rewritten, using token positions rather than substring
    scanning (R6.21). Returns the rewritten SQL and the number of placeholders
    replaced. A bare ``%`` that is not part of a ``%s`` marker is left in place so
    that parsing fails and the firewall reports ``UNPARSEABLE`` (R6.20).
    """
    try:
        raw: list[Token] = sqlglot.tokenize(sql, read=_DIALECT)
    except TokenError:
        # Let the caller's parse step raise UNPARSEABLE; return unchanged.
        return sql, 0

    # Character spans covered by literal/identifier tokens are protected.
    protected: list[tuple[int, int]] = [
        (tok.start, tok.end)
        for tok in raw
        if tok.token_type in _LITERAL_TOKEN_TYPES
    ]

    def _is_protected(index: int) -> bool:
        return any(start <= index <= end for start, end in protected)

    out: list[str] = []
    count = 0
    i = 0
    length = len(sql)
    while i < length:
        if sql[i] == "%" and i + 1 < length and sql[i + 1] == "s":
            if not _is_protected(i):
                out.append(f":p{count}")
                count += 1
                i += 2
                continue
        out.append(sql[i])
        i += 1
    return "".join(out), count


# ── AST inspection surface (keeps sqlglot's exp inside this module, B1) ────────


@dataclass(frozen=True, slots=True)
class TableRef:
    """A table reference: its name and its (possibly empty) schema qualifier."""

    name: str
    schema: str


@dataclass(frozen=True, slots=True)
class ColumnRef:
    """A column reference: its name and its (possibly empty) table qualifier."""

    name: str
    table: str


@dataclass(frozen=True, slots=True)
class LimitInfo:
    """The outermost LIMIT: whether present, an integer literal, and its value."""

    present: bool
    is_integer_literal: bool
    value: int | None


class Analysis:
    """Computed, parser-independent facts about one parsed statement.

    Every attribute the firewall's AST checks need is exposed here, so the
    firewall never imports sqlglot's ``exp`` directly (import boundary B1).
    """

    def __init__(self, tree: SqlTree) -> None:
        root = tree.root
        self.statement_count: int = len(tree.statements)
        self.data_modifying_cte: bool = any(
            isinstance(cte.this, DML_TYPES) for cte in root.find_all(exp.CTE)
        )
        self.nested_dml: bool = any(True for _ in root.find_all(*DML_TYPES))
        self.select_rooted: bool = _is_select_rooted(root)
        self.select_into: bool = any(
            s.args.get("into") is not None for s in root.find_all(exp.Select)
        )
        self.locking_clause: bool = any(
            bool(s.args.get("locks")) for s in root.find_all(exp.Select)
        )
        self.tables: tuple[TableRef, ...] = tuple(
            TableRef(name=n.name, schema=n.db) for n in root.find_all(exp.Table)
        )
        self.columns: tuple[ColumnRef, ...] = tuple(
            ColumnRef(name=n.name, table=n.table) for n in root.find_all(exp.Column)
        )
        self.function_names: tuple[str, ...] = tuple(
            _func_name(n)
            for n in root.find_all(exp.Func)
            if not isinstance(n, (exp.Binary, exp.Connector))
        )
        self.limit: LimitInfo = _outer_limit(root)
        self.offset_non_literal: bool = _offset_non_literal(root)
        self.join_without_predicate: bool = any(
            j.args.get("on") is None and j.args.get("using") is None
            for j in root.find_all(exp.Join)
        )
        self.join_count: int = sum(1 for _ in root.find_all(exp.Join))
        self.subquery_depth: int = _max_subquery_depth(root)
        set_ops = list(root.find_all(exp.Union, exp.Intersect, exp.Except))
        self.set_operation_arms: int = len(set_ops) + 1 if set_ops else 1
        self.inline_string_literals: tuple[str, ...] = tuple(
            n.name for n in root.find_all(exp.Literal) if n.args.get("is_string")
        )
        self.placeholder_count: int = sum(
            1 for _ in root.find_all(exp.Placeholder)
        )


def analyze(sql: str) -> Analysis:
    """Parse ``sql`` and return its computed ``Analysis`` (raises on parse error)."""
    return Analysis(parse(sql))


def _func_name(node: exp.Func) -> str:
    """Return the lowercased callable name of a function node.

    ``exp.Anonymous`` (an unrecognized function such as ``pg_sleep``) carries its
    name in ``.name``; recognized functions expose it through ``sql_name()``.
    """
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    name = node.sql_name() if hasattr(node, "sql_name") else type(node).__name__
    return name.lower()


def _is_select_rooted(root: exp.Expression) -> bool:
    query_types = (exp.Select, exp.Union, exp.Intersect, exp.Except)
    if not isinstance(root, query_types):
        return False
    return all(isinstance(cte.this, query_types) for cte in root.find_all(exp.CTE))


def _outer_limit(root: exp.Expression) -> LimitInfo:
    limit = root.args.get("limit")
    if limit is None:
        return LimitInfo(present=False, is_integer_literal=False, value=None)
    expr = limit.expression
    if isinstance(expr, exp.Literal) and not expr.args.get("is_string"):
        try:
            return LimitInfo(True, True, int(expr.name))
        except ValueError:
            return LimitInfo(True, False, None)
    return LimitInfo(present=True, is_integer_literal=False, value=None)


def _offset_non_literal(root: exp.Expression) -> bool:
    offset = root.args.get("offset")
    if offset is None:
        return False
    expr = offset.expression
    if isinstance(expr, exp.Literal) and not expr.args.get("is_string"):
        try:
            return int(expr.name) < 0
        except ValueError:
            return True
    return True


def _subquery_ancestor_count(node: exp.Expression) -> int:
    depth = 0
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.Subquery):
            depth += 1
        parent = parent.parent
    return depth


def _max_subquery_depth(root: exp.Expression) -> int:
    depths = [
        _subquery_ancestor_count(node) + 1 for node in root.find_all(exp.Subquery)
    ]
    return max(depths, default=0)
