"""Unit tests for kognit_llm.safety.firewall.

Drive ``validate_sql`` across the ADMIT path and every reachable REJECT reason,
and bind-by-sha256 behavior. A handful of statement-shape branches cannot be
reached through parsing (a data-modifying CTE is never select-rooted, so
NOT_SELECT fires first); those are exercised by calling the ordered-check helper
directly with an Analysis whose flags are set, which keeps full line coverage
without touching src. All inputs are pure SQL text; no warehouse or network.
"""

import hashlib

from kognit_llm.safety import firewall
from kognit_llm.safety.firewall import (
    FirewallLimits,
    FirewallVerdict,
    validate_sql,
)
from kognit_llm.safety.reason_codes import RejectionReason
from kognit_llm.safety.sql_ast import Analysis, analyze
from kognit_llm.schema.allowlist import AllowList, load_allowlist


def _allowlist() -> AllowList:
    return load_allowlist()


def _limits() -> FirewallLimits:
    return FirewallLimits(
        row_cap=1000,
        max_statement_chars=10_000,
        max_join_count=5,
        max_subquery_depth=5,
        max_set_operation_arms=5,
    )


def _validate(
    statement: str,
    params: "list[firewall.BoundParam] | None" = None,
    *,
    user_message: str = "",
    limits: FirewallLimits | None = None,
) -> FirewallVerdict:
    allowlist = _allowlist()
    return validate_sql(
        statement,
        params if params is not None else [],
        allowlist=allowlist,
        functions=allowlist.functions,
        limits=limits if limits is not None else _limits(),
        approved_schema=allowlist.approved_schema,
        user_message=user_message,
    )


def test_public_all_exports() -> None:
    for name in firewall.__all__:
        assert hasattr(firewall, name)


# ── ADMIT path and hash binding ─────────────────────────────────────────────


def test_admit_simple_select() -> None:
    sql = "SELECT record_no FROM fact_incidents LIMIT 10"
    verdict = _validate(sql)
    assert verdict.verdict == "ADMIT"
    assert verdict.reason is None


def test_admit_statement_hash_matches_original_text() -> None:
    sql = "SELECT record_no FROM fact_incidents LIMIT 10"
    verdict = _validate(sql)
    expected = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    assert verdict.statement_sha256 == expected


def test_reject_hash_also_binds_to_original_text() -> None:
    sql = "DELETE FROM fact_incidents"
    verdict = _validate(sql)
    expected = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    assert verdict.statement_sha256 == expected
    assert verdict.verdict == "REJECT"


def test_admit_with_approved_function_and_join_predicate() -> None:
    sql = (
        "SELECT count(record_no) FROM fact_incidents "
        "JOIN dim_date ON fact_incidents.sk_date = dim_date.sk_date "
        "LIMIT 10"
    )
    verdict = _validate(sql)
    assert verdict.verdict == "ADMIT"


def test_admit_with_parameterized_placeholder() -> None:
    sql = "SELECT record_no FROM fact_incidents WHERE sk_date = %s LIMIT 10"
    verdict = _validate(sql, params=[5])
    assert verdict.verdict == "ADMIT"


# ── token-stream rejections ─────────────────────────────────────────────────


def test_reject_empty_statement() -> None:
    assert _validate("   ").reason is RejectionReason.EMPTY_STATEMENT


def test_reject_statement_too_long() -> None:
    sql = "SELECT record_no FROM fact_incidents LIMIT 10"
    limits = FirewallLimits(
        row_cap=1000,
        max_statement_chars=5,
        max_join_count=5,
        max_subquery_depth=5,
        max_set_operation_arms=5,
    )
    assert _validate(sql, limits=limits).reason is (
        RejectionReason.COMPLEXITY_EXCEEDED
    )


def test_reject_comment_present() -> None:
    sql = "SELECT record_no FROM fact_incidents LIMIT 10 -- sneaky"
    assert _validate(sql).reason is RejectionReason.COMMENT_PRESENT


def test_reject_separator_present() -> None:
    sql = "SELECT record_no FROM fact_incidents LIMIT 10; SELECT 1"
    assert _validate(sql).reason is RejectionReason.SEPARATOR_PRESENT


def test_reject_forbidden_keyword() -> None:
    assert _validate("DROP TABLE fact_incidents").reason is (
        RejectionReason.FORBIDDEN_KEYWORD
    )


def test_reject_unparseable_at_parse_step() -> None:
    assert _validate("SELECT FROM WHERE )(").reason is (
        RejectionReason.UNPARSEABLE
    )


def test_reject_unparseable_at_tokenize_step() -> None:
    # An unterminated string literal fails at the first tokenize call.
    assert _validate("SELECT 'oops FROM t").reason is (
        RejectionReason.UNPARSEABLE
    )


def test_reject_unparseable_after_bad_placeholder_normalization() -> None:
    # A bare % that is not %s survives normalization and fails parsing.
    sql = "SELECT record_no % FROM fact_incidents LIMIT 10"
    assert _validate(sql).reason is RejectionReason.UNPARSEABLE


# ── statement-shape rejections (reachable via parsing) ──────────────────────


def test_reject_not_select() -> None:
    # A bare SELECT without a forbidden keyword token: a VALUES statement.
    assert _validate("VALUES (1)").reason is RejectionReason.NOT_SELECT


def test_reject_select_into() -> None:
    sql = "SELECT record_no INTO tmp FROM fact_incidents LIMIT 10"
    assert _validate(sql).reason is RejectionReason.SELECT_INTO


# ── schema / table / column rejections ──────────────────────────────────────


def test_reject_system_catalog_reference() -> None:
    sql = "SELECT relname FROM pg_class LIMIT 10"
    assert _validate(sql).reason is RejectionReason.SYSTEM_CATALOG_REFERENCE


def test_reject_system_catalog_information_schema() -> None:
    sql = "SELECT table_name FROM information_schema.tables LIMIT 10"
    assert _validate(sql).reason is RejectionReason.SYSTEM_CATALOG_REFERENCE


def test_reject_unapproved_schema() -> None:
    sql = "SELECT record_no FROM other.fact_incidents LIMIT 10"
    assert _validate(sql).reason is RejectionReason.UNAPPROVED_SCHEMA


def test_reject_unapproved_table() -> None:
    sql = "SELECT a FROM not_a_real_table LIMIT 10"
    assert _validate(sql).reason is RejectionReason.UNAPPROVED_TABLE


def test_reject_unapproved_column_qualified() -> None:
    sql = "SELECT fact_incidents.nope FROM fact_incidents LIMIT 10"
    assert _validate(sql).reason is RejectionReason.UNAPPROVED_COLUMN


def test_reject_unapproved_column_unqualified() -> None:
    sql = "SELECT nope FROM fact_incidents LIMIT 10"
    assert _validate(sql).reason is RejectionReason.UNAPPROVED_COLUMN


def test_admit_star_column_skipped() -> None:
    # '*' is not subject to column allow-listing.
    sql = "SELECT * FROM fact_incidents LIMIT 10"
    assert _validate(sql).verdict == "ADMIT"


def test_admit_qualified_star_column_skipped() -> None:
    # A qualified star (fact_incidents.*) is a column named '*' and is skipped.
    sql = "SELECT fact_incidents.* FROM fact_incidents LIMIT 10"
    assert _validate(sql).verdict == "ADMIT"


# ── function rejections ──────────────────────────────────────────────────────


def test_reject_forbidden_function() -> None:
    sql = "SELECT pg_sleep(1) FROM fact_incidents LIMIT 10"
    assert _validate(sql).reason is RejectionReason.FORBIDDEN_FUNCTION


def test_reject_unapproved_function() -> None:
    sql = "SELECT upper(record_no) FROM fact_incidents LIMIT 10"
    assert _validate(sql).reason is RejectionReason.UNAPPROVED_FUNCTION


# ── limit / offset / complexity rejections ──────────────────────────────────


def test_reject_missing_limit() -> None:
    sql = "SELECT record_no FROM fact_incidents"
    assert _validate(sql).reason is RejectionReason.MISSING_LIMIT


def test_reject_non_literal_limit() -> None:
    sql = "SELECT record_no FROM fact_incidents LIMIT 'x'"
    assert _validate(sql).reason is RejectionReason.NON_LITERAL_LIMIT


def test_reject_negative_limit_non_literal() -> None:
    sql = "SELECT record_no FROM fact_incidents LIMIT -5"
    assert _validate(sql).reason is RejectionReason.NON_LITERAL_LIMIT


def test_reject_limit_exceeds_row_cap() -> None:
    sql = "SELECT record_no FROM fact_incidents LIMIT 100000"
    assert _validate(sql).reason is RejectionReason.LIMIT_EXCEEDS_ROW_CAP


def test_reject_non_literal_offset() -> None:
    sql = "SELECT record_no FROM fact_incidents LIMIT 10 OFFSET -1"
    assert _validate(sql).reason is RejectionReason.NON_LITERAL_OFFSET


def test_reject_missing_join_predicate() -> None:
    sql = (
        "SELECT record_no FROM fact_incidents "
        "JOIN dim_date LIMIT 10"
    )
    assert _validate(sql).reason is RejectionReason.MISSING_JOIN_PREDICATE


def test_reject_complexity_exceeded_joins() -> None:
    sql = (
        "SELECT fact_incidents.record_no FROM fact_incidents "
        "JOIN dim_date ON fact_incidents.sk_date = dim_date.sk_date "
        "JOIN dim_location ON fact_incidents.sk_location = "
        "dim_location.sk_location "
        "JOIN dim_incident_type ON fact_incidents.sk_type = "
        "dim_incident_type.sk_type "
        "LIMIT 10"
    )
    limits = FirewallLimits(
        row_cap=1000,
        max_statement_chars=10_000,
        max_join_count=1,
        max_subquery_depth=5,
        max_set_operation_arms=5,
    )
    assert _validate(sql, limits=limits).reason is (
        RejectionReason.COMPLEXITY_EXCEEDED
    )


# ── parameterization rejections ─────────────────────────────────────────────


def test_reject_placeholder_param_count_mismatch() -> None:
    sql = "SELECT record_no FROM fact_incidents WHERE sk_date = %s LIMIT 10"
    # One placeholder but zero params.
    assert _validate(sql, params=[]).reason is (
        RejectionReason.UNPARAMETERIZED_LITERAL
    )


def test_reject_inline_literal_from_user_message() -> None:
    # A string literal present verbatim in the user message is unparameterized.
    sql = "SELECT record_no FROM fact_incidents WHERE sk_date = 'acme' LIMIT 10"
    verdict = _validate(sql, user_message="tell me about acme please")
    assert verdict.reason is RejectionReason.UNPARAMETERIZED_LITERAL


def test_admit_inline_literal_not_in_user_message() -> None:
    sql = "SELECT record_no FROM fact_incidents WHERE sk_date = 'xyz' LIMIT 10"
    verdict = _validate(sql, user_message="completely unrelated text")
    assert verdict.verdict == "ADMIT"


# ── statement-shape branches unreachable via parsing ────────────────────────
#
# A data-modifying CTE / nested DML / locking clause can coexist with a
# select-rooted root only in a constructed Analysis; through parsing the root is
# no longer select-rooted and NOT_SELECT fires first. Exercise the ordered
# helper directly so the DATA_MODIFYING_CTE / NESTED_DML / LOCKING_CLAUSE /
# MULTIPLE_STATEMENTS lines are covered.


def _select_rooted_analysis() -> Analysis:
    return analyze("SELECT record_no FROM fact_incidents LIMIT 10")


def test_shape_multiple_statements_branch() -> None:
    a = _select_rooted_analysis()
    a.statement_count = 2
    assert firewall._check_statement_shape(a) is (
        RejectionReason.MULTIPLE_STATEMENTS
    )


def test_shape_data_modifying_cte_branch() -> None:
    a = _select_rooted_analysis()
    a.data_modifying_cte = True
    assert firewall._check_statement_shape(a) is (
        RejectionReason.DATA_MODIFYING_CTE
    )


def test_shape_nested_dml_branch() -> None:
    a = _select_rooted_analysis()
    a.nested_dml = True
    assert firewall._check_statement_shape(a) is RejectionReason.NESTED_DML


def test_shape_locking_clause_branch() -> None:
    a = _select_rooted_analysis()
    a.locking_clause = True
    assert firewall._check_statement_shape(a) is (
        RejectionReason.LOCKING_CLAUSE
    )


def test_shape_all_ok_returns_none() -> None:
    a = _select_rooted_analysis()
    assert firewall._check_statement_shape(a) is None


def test_limit_zero_still_admits() -> None:
    # Guards the `value is not None` branch of the row-cap/negative checks.
    sql = "SELECT record_no FROM fact_incidents LIMIT 0"
    assert _validate(sql).verdict == "ADMIT"
