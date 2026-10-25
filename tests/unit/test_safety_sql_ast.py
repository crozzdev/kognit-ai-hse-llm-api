"""Unit tests for kognit_llm.safety.sql_ast.

Exercise tokenize/parse/analyze/normalize_placeholders plus the private AST
helpers so both the happy path and the error/edge branches are covered. All
inputs are pure in-process SQL text; no network or warehouse access.
"""

import pytest

from kognit_llm.safety import sql_ast
from kognit_llm.safety.sql_ast import (
    Analysis,
    ColumnRef,
    LimitInfo,
    SqlAstError,
    SqlToken,
    TableRef,
    analyze,
    normalize_placeholders,
    parse,
    tokenize,
)


def test_public_all_exports() -> None:
    for name in sql_ast.__all__:
        assert hasattr(sql_ast, name)


# ── tokenize ──────────────────────────────────────────────────────────────


def test_tokenize_returns_project_tokens() -> None:
    tokens = tokenize("SELECT 1")
    assert all(isinstance(t, SqlToken) for t in tokens)
    assert tokens[0].token_type == "SELECT"
    assert tokens[0].text == "SELECT"


def test_tokenize_marks_comment_carrier() -> None:
    tokens = tokenize("SELECT 1 -- trailing comment")
    assert any(t.is_comment_carrier for t in tokens)


def test_tokenize_whitespace_only_has_no_tokens() -> None:
    assert tokenize("   ") == []


def test_tokenize_raises_sql_ast_error_on_bad_token() -> None:
    with pytest.raises(SqlAstError):
        tokenize("SELECT 'unterminated string")


# ── parse ─────────────────────────────────────────────────────────────────


def test_parse_single_statement() -> None:
    tree = parse("SELECT 1")
    assert len(tree.statements) == 1
    assert tree.root is tree.statements[0]


def test_parse_multiple_statements() -> None:
    tree = parse("SELECT 1; SELECT 2")
    assert len(tree.statements) == 2


def test_parse_raises_on_syntax_error() -> None:
    with pytest.raises(SqlAstError):
        parse("SELECT FROM WHERE )(")


def test_parse_raises_when_no_statement() -> None:
    # A lone comment yields no parseable statement.
    with pytest.raises(SqlAstError):
        parse("-- only a comment")


# ── normalize_placeholders ──────────────────────────────────────────────────


def test_normalize_replaces_placeholder_outside_literal() -> None:
    out, count = normalize_placeholders("SELECT * FROM t WHERE a = %s LIMIT 10")
    assert count == 1
    assert ":p0" in out
    assert "%s" not in out


def test_normalize_multiple_placeholders_numbered() -> None:
    out, count = normalize_placeholders(
        "SELECT * FROM t WHERE a = %s AND b = %s LIMIT 10"
    )
    assert count == 2
    assert ":p0" in out
    assert ":p1" in out


def test_normalize_protects_placeholder_inside_string_literal() -> None:
    out, count = normalize_placeholders("SELECT '%s' FROM t")
    assert count == 0
    assert out == "SELECT '%s' FROM t"


def test_normalize_no_placeholders_unchanged() -> None:
    out, count = normalize_placeholders("SELECT 1")
    assert count == 0
    assert out == "SELECT 1"


def test_normalize_bare_percent_left_in_place() -> None:
    # A bare % that is not part of %s is not rewritten.
    out, count = normalize_placeholders("SELECT a % b FROM t LIMIT 1")
    assert count == 0
    assert "%" in out


def test_normalize_tokenizer_error_returns_unchanged() -> None:
    # Unterminated literal makes the tokenizer raise; normalize returns as-is.
    original = "SELECT 'unterminated %s"
    out, count = normalize_placeholders(original)
    assert out == original
    assert count == 0


# ── analyze: happy path and structural facts ──────────────────────────────


def test_analyze_simple_select_facts() -> None:
    a = analyze("SELECT count(*) FROM fact_incidents LIMIT 10")
    assert a.statement_count == 1
    assert a.select_rooted is True
    assert a.nested_dml is False
    assert a.data_modifying_cte is False
    assert a.function_names == ("count",)
    assert a.tables == (TableRef(name="fact_incidents", schema=""),)
    assert a.limit == LimitInfo(present=True, is_integer_literal=True, value=10)


def test_analyze_qualified_table_and_columns() -> None:
    a = analyze("SELECT public.t.x FROM public.t LIMIT 1")
    assert any(t.schema == "public" and t.name == "t" for t in a.tables)
    assert any(isinstance(c, ColumnRef) for c in a.columns)


def test_analyze_detects_select_into() -> None:
    a = analyze("SELECT a INTO foo FROM t LIMIT 10")
    assert a.select_into is True


def test_analyze_detects_locking_clause() -> None:
    a = analyze("SELECT a FROM t FOR UPDATE LIMIT 10")
    assert a.locking_clause is True


def test_analyze_data_modifying_cte_and_nested_dml() -> None:
    a = analyze("WITH x AS (DELETE FROM t RETURNING a) SELECT * FROM x LIMIT 1")
    assert a.data_modifying_cte is True
    assert a.nested_dml is True
    # A data-modifying CTE is not select-rooted.
    assert a.select_rooted is False


def test_analyze_non_select_root_not_select_rooted() -> None:
    a = analyze("UPDATE t SET a = 1")
    assert a.select_rooted is False
    assert a.nested_dml is True


def test_analyze_join_without_predicate_and_count() -> None:
    a = analyze("SELECT a FROM t1 JOIN t2 LIMIT 5")
    assert a.join_without_predicate is True
    assert a.join_count == 1


def test_analyze_join_with_predicate() -> None:
    a = analyze("SELECT a FROM t1 JOIN t2 ON t1.k = t2.k LIMIT 5")
    assert a.join_without_predicate is False
    assert a.join_count == 1


def test_analyze_subquery_depth() -> None:
    a = analyze(
        "SELECT a FROM (SELECT b FROM (SELECT c FROM t) x) y LIMIT 1"
    )
    assert a.subquery_depth == 2


def test_analyze_set_operation_arms() -> None:
    a = analyze("SELECT 1 UNION SELECT 2 UNION SELECT 3")
    assert a.set_operation_arms == 3
    assert a.select_rooted is True


def test_analyze_single_select_has_one_arm() -> None:
    a = analyze("SELECT a FROM t LIMIT 1")
    assert a.set_operation_arms == 1


def test_analyze_inline_string_literals() -> None:
    a = analyze("SELECT a FROM t WHERE name = 'bob' LIMIT 10")
    assert "bob" in a.inline_string_literals


def test_analyze_placeholder_count() -> None:
    a = analyze("SELECT a FROM t WHERE a = :p0 LIMIT 10")
    assert a.placeholder_count == 1


def test_analyze_raises_on_parse_error() -> None:
    with pytest.raises(SqlAstError):
        analyze("SELECT FROM WHERE )(")


# ── LIMIT / OFFSET edge branches ────────────────────────────────────────────


def test_limit_absent() -> None:
    a = analyze("SELECT a FROM t")
    assert a.limit == LimitInfo(present=False, is_integer_literal=False, value=None)


def test_limit_non_integer_literal_string() -> None:
    a = analyze("SELECT a FROM t LIMIT 'x'")
    assert a.limit.present is True
    assert a.limit.is_integer_literal is False
    assert a.limit.value is None


def test_limit_negative_is_not_integer_literal() -> None:
    # A negative LIMIT parses as a Neg node, not a bare integer literal.
    a = analyze("SELECT a FROM t LIMIT -5")
    assert a.limit.present is True
    assert a.limit.is_integer_literal is False


def test_offset_negative_is_non_literal() -> None:
    a = analyze("SELECT a FROM t LIMIT 10 OFFSET -1")
    assert a.offset_non_literal is True


def test_offset_literal_ok() -> None:
    a = analyze("SELECT a FROM t LIMIT 10 OFFSET 5")
    assert a.offset_non_literal is False


def test_offset_absent_is_false() -> None:
    a = analyze("SELECT a FROM t LIMIT 10")
    assert a.offset_non_literal is False


def test_offset_placeholder_is_non_literal() -> None:
    a = analyze("SELECT a FROM t LIMIT 10 OFFSET :p0")
    assert a.offset_non_literal is True


def test_limit_float_literal_not_integer() -> None:
    # A non-string numeric literal that int() cannot parse (float path).
    a = analyze("SELECT a FROM t LIMIT 1.5")
    assert a.limit.present is True
    assert a.limit.is_integer_literal is False
    assert a.limit.value is None


def test_offset_float_literal_is_non_literal() -> None:
    a = analyze("SELECT a FROM t LIMIT 10 OFFSET 1.5")
    assert a.offset_non_literal is True


# ── Analysis is a plain, inspectable object ────────────────────────────────


def test_analysis_type_is_analysis() -> None:
    a = analyze("SELECT a FROM t LIMIT 1")
    assert isinstance(a, Analysis)
