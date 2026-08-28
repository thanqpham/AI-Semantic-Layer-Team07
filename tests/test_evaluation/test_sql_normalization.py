"""Tests for SQL AST canonicalization and safety validation."""

import pytest

from eval.evaluator.sql_normalization import (
    SqlValidationError,
    canonical_sql,
    normalize_sql,
    structurally_equal,
)


def test_format_and_table_alias_are_equivalent() -> None:
    left = "SELECT o.id AS order_id FROM orders AS o WHERE o.id = 1"
    right = " select id from orders where id=1 "
    assert structurally_equal(left, right)


def test_different_predicate_is_not_equivalent() -> None:
    assert not structurally_equal("SELECT id FROM orders WHERE id = 1", "SELECT id FROM orders WHERE id = 2")


def test_different_join_column_source_is_not_equivalent() -> None:
    left = "SELECT a.id FROM foo a JOIN bar b ON a.id = b.id"
    right = "SELECT b.id FROM foo a JOIN bar b ON a.id = b.id"
    assert not structurally_equal(left, right)


def test_different_join_condition_is_not_equivalent() -> None:
    left = "SELECT a.id FROM foo a JOIN bar b ON a.id = b.id"
    right = "SELECT a.id FROM foo a JOIN bar b ON a.id = a.id"
    assert not structurally_equal(left, right)


def test_postgresql_contract_dialect_maps_to_sqlglot() -> None:
    sql = "SELECT DATE_TRUNC('month', created_at) FROM orders"
    assert normalize_sql(sql, "postgresql").canonical


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT 1; SELECT 2",
        "SELECT id INTO backup FROM orders",
        "SELECT readfile('/tmp/secret')",
        "WITH removed AS (DELETE FROM orders RETURNING id) SELECT * FROM removed",
    ],
)
def test_unsafe_or_multi_statement_is_rejected(sql: str) -> None:
    with pytest.raises(SqlValidationError):
        normalize_sql(sql)


def test_mixed_multi_statement_prioritizes_non_select_error() -> None:
    with pytest.raises(SqlValidationError, match="NON_SELECT_STATEMENT"):
        normalize_sql("SELECT * FROM orders; DELETE FROM customers")


def test_data_modifying_cte_reports_nested_dml() -> None:
    sql = "WITH removed AS (DELETE FROM orders RETURNING id) SELECT * FROM removed"
    with pytest.raises(SqlValidationError, match="NESTED_DML"):
        normalize_sql(sql)


def test_multiple_selects_report_multi_statement() -> None:
    with pytest.raises(SqlValidationError, match="MULTI_STATEMENT"):
        normalize_sql("SELECT 1; SELECT 2")


def test_structurally_equal_ignore_limit():
    from eval.evaluator.sql_normalization import structurally_equal

    assert structurally_equal("SELECT 1 AS x", "SELECT 1 AS x LIMIT 100", "sqlite", ignore_limit=True)
    assert not structurally_equal("SELECT 1 AS x", "SELECT 1 AS x LIMIT 100", "sqlite")
    assert structurally_equal("SELECT 1 AS x LIMIT 5", "SELECT 1 AS x LIMIT 100", "sqlite", ignore_limit=True)
    assert not structurally_equal("SELECT 1 AS x", "SELECT 2 AS x", "sqlite", ignore_limit=True)


def test_normalize_expression_boolean_literals_are_integers():
    from eval.evaluator.sql_normalization import normalize_expression

    assert normalize_expression("is_test_order = FALSE") == normalize_expression("is_test_order = 0")
    assert normalize_expression("is_bot_traffic = TRUE") == normalize_expression("is_bot_traffic = 1")


def test_normalize_sql_boolean_literals_are_integers():
    from eval.evaluator.sql_normalization import normalize_sql

    left = normalize_sql("SELECT 1 FROM t WHERE is_test_order = FALSE", "sqlite").canonical
    right = normalize_sql("SELECT 1 FROM t WHERE is_test_order = 0", "sqlite").canonical
    assert left == right


def test_structurally_equal_ignore_limit_combined_with_aliases_and_booleans():
    from eval.evaluator.sql_normalization import structurally_equal

    left = "SELECT SUM(a - b) AS net_revenue FROM fact_orders WHERE is_test_order = FALSE"
    right = "SELECT SUM(a - b) AS metric_1 FROM fact_orders WHERE is_test_order = 0 LIMIT 100"
    assert structurally_equal(left, right, "sqlite", ignore_limit=True)


def test_structurally_equal_ignore_limit_also_ignores_order_by():
    from eval.evaluator.sql_normalization import structurally_equal

    # Golden shape (GROUP BY + ORDER BY + LIMIT) vs product shape (no ORDER BY/LIMIT).
    left = (
        "SELECT channel, COUNT(order_id) AS order_count FROM fact_orders "
        "WHERE is_test_order = FALSE GROUP BY channel ORDER BY channel LIMIT 100"
    )
    right = "SELECT channel, COUNT(order_id) AS order_count FROM fact_orders WHERE is_test_order = 0 GROUP BY channel"
    assert structurally_equal(left, right, "sqlite", ignore_limit=True)


def test_structurally_equal_order_by_difference_matters_by_default():
    from eval.evaluator.sql_normalization import structurally_equal

    left = "SELECT id FROM orders ORDER BY id"
    right = "SELECT id FROM orders ORDER BY name"
    assert not structurally_equal(left, right, "sqlite")


def test_structurally_equal_limit_value_difference_matters_by_default():
    from eval.evaluator.sql_normalization import structurally_equal

    assert not structurally_equal("SELECT 1 AS x LIMIT 5", "SELECT 1 AS x LIMIT 100", "sqlite")


# ---------------------------------------------------------------------------
# identifier quoting is rendering, not semantics (SQLite)
# ---------------------------------------------------------------------------


def test_quoted_and_unquoted_identifiers_compare_equal() -> None:
    quoted = 'SELECT "fact_orders"."amount" FROM "fact_orders" WHERE "fact_orders"."is_test" = 0'
    bare = "SELECT amount FROM fact_orders WHERE is_test = 0"
    assert structurally_equal(quoted, bare, "sqlite", ignore_limit=True)


def test_quoting_fix_does_not_equate_different_columns() -> None:
    quoted = 'SELECT "fact_orders"."amount" FROM "fact_orders"'
    other = 'SELECT "fact_orders"."total" FROM "fact_orders"'
    assert not structurally_equal(quoted, other, "sqlite", ignore_limit=True)


def test_quoting_fix_does_not_equate_different_literals() -> None:
    quoted = "SELECT amount FROM fact_orders WHERE flag = '0'"
    other = "SELECT amount FROM fact_orders WHERE flag = 0"
    assert not structurally_equal(quoted, other, "sqlite", ignore_limit=True)


def test_quoting_fix_does_not_equate_different_tables() -> None:
    quoted = 'SELECT "amount" FROM "fact_orders"'
    other = 'SELECT "amount" FROM "fact_carts"'
    assert not structurally_equal(quoted, other, "sqlite", ignore_limit=True)


# ---------------------------------------------------------------------------
# locking reads are not read-only (fail-closed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "dialect"),
    [
        ("SELECT id FROM orders WHERE store_id = 1 FOR UPDATE", "postgres"),
        ("SELECT id FROM orders WHERE store_id = 1 FOR SHARE", "postgres"),
        ("SELECT id FROM orders LOCK IN SHARE MODE", "mysql"),
    ],
)
def test_locking_reads_are_rejected(sql: str, dialect: str) -> None:
    with pytest.raises(SqlValidationError, match="UNSAFE_SQL"):
        normalize_sql(sql, dialect)  # type: ignore[arg-type]


def test_plain_select_still_accepted_after_lock_check() -> None:
    canonical = normalize_sql("SELECT id FROM orders WHERE store_id = 1", "postgres")
    assert canonical.canonical.startswith("SELECT")


# ---------------------------------------------------------------------------
# canonical_sql is exactly what structurally_equal compares
# ---------------------------------------------------------------------------


def test_canonical_sql_matches_structural_equality_decision() -> None:
    left = 'SELECT "amount" FROM "orders" WHERE flag = FALSE ORDER BY amount LIMIT 100'
    right = "SELECT amount FROM orders WHERE flag = 0"
    assert canonical_sql(left, "sqlite", ignore_limit=True) == canonical_sql(right, "sqlite", ignore_limit=True)
    assert structurally_equal(left, right, "sqlite", ignore_limit=True)
    # Without the presentation strip the two sides genuinely differ.
    assert canonical_sql(left, "sqlite") != canonical_sql(right, "sqlite")


def test_canonical_sql_keeps_semantic_difference_visible() -> None:
    assert canonical_sql("SELECT id FROM orders WHERE id = 1") != canonical_sql("SELECT id FROM orders WHERE id = 2")


# ---------------------------------------------------------------------------
# conditional aggregates: AGG(CASE WHEN f THEN x END) ≡ AGG(x) WHERE f
# ---------------------------------------------------------------------------


def test_where_form_matches_case_form_without_group_by() -> None:
    case_form = "SELECT SUM(CASE WHEN is_test_order = 0 THEN amount END) FROM fact_orders"
    where_form = "SELECT SUM(amount) FROM fact_orders WHERE is_test_order = 0"
    assert structurally_equal(case_form, where_form, "sqlite", ignore_limit=True)


def test_where_form_matches_case_form_with_group_by() -> None:
    case_form = "SELECT channel, SUM(CASE WHEN is_test_order = 0 THEN amount END) FROM fact_orders GROUP BY channel"
    where_form = "SELECT channel, SUM(amount) FROM fact_orders WHERE is_test_order = 0 GROUP BY channel"
    assert structurally_equal(case_form, where_form, "sqlite", ignore_limit=True)


def test_arithmetic_over_multiple_aggregates_matches() -> None:
    case_form = (
        "SELECT SUM(CASE WHEN f = 0 THEN a END) * 1.0 / NULLIF(COUNT(DISTINCT CASE WHEN f = 0 THEN o END), 0) FROM t"
    )
    where_form = "SELECT SUM(a) * 1.0 / NULLIF(COUNT(DISTINCT o), 0) FROM t WHERE f = 0"
    assert structurally_equal(case_form, where_form, "sqlite", ignore_limit=True)


def test_count_star_where_form_matches_case_one() -> None:
    assert structurally_equal(
        "SELECT COUNT(CASE WHEN f = 0 THEN 1 END) FROM t",
        "SELECT COUNT(*) FROM t WHERE f = 0",
        "sqlite",
        ignore_limit=True,
    )


def test_joined_where_form_matches_case_form() -> None:
    case_form = (
        "SELECT c.city, SUM(CASE WHEN o.is_test = 0 THEN o.amount END) "
        "FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.city"
    )
    where_form = (
        "SELECT c.city, SUM(o.amount) FROM orders o JOIN customers c "
        "ON o.customer_id = c.id WHERE o.is_test = 0 GROUP BY c.city"
    )
    assert structurally_equal(case_form, where_form, "sqlite", ignore_limit=True)


def test_both_sides_in_where_form_still_match_each_other() -> None:
    left = "SELECT SUM(a) FROM t WHERE f = 0"
    right = "SELECT SUM(a) FROM t WHERE f = FALSE"
    assert structurally_equal(left, right, "sqlite", ignore_limit=True)


def test_different_conditions_stay_unequal() -> None:
    case_form = "SELECT COUNT(DISTINCT CASE WHEN is_test_order = 0 THEN customer_id END) FROM fact_orders"
    where_form = "SELECT COUNT(DISTINCT customer_id) FROM fact_orders WHERE is_test_order = 0 AND is_canceled = 0"
    assert not structurally_equal(case_form, where_form, "sqlite", ignore_limit=True)


def test_case_with_else_zero_stays_unequal_to_where() -> None:
    # ELSE 0 feeds zeros into the aggregate; the WHERE/NULL form does not.
    assert not structurally_equal(
        "SELECT SUM(CASE WHEN f = 0 THEN a ELSE 0 END) FROM t",
        "SELECT SUM(a) FROM t WHERE f = 0",
        "sqlite",
        ignore_limit=True,
    )


def test_where_without_aggregates_is_not_rewritten() -> None:
    assert not structurally_equal(
        "SELECT id FROM orders", "SELECT id FROM orders WHERE id > 1", "sqlite", ignore_limit=True
    )


def test_union_where_form_is_not_rewritten() -> None:
    where_union = "SELECT SUM(a) FROM t1 WHERE f = 0 UNION SELECT SUM(a) FROM t2 WHERE f = 0"
    case_union = "SELECT SUM(CASE WHEN f = 0 THEN a END) FROM t1 UNION SELECT SUM(CASE WHEN f = 0 THEN a END) FROM t2"
    assert not structurally_equal(where_union, case_union, "sqlite", ignore_limit=True)


def test_window_where_form_is_not_rewritten() -> None:
    assert not structurally_equal(
        "SELECT SUM(CASE WHEN f = 0 THEN a END) OVER () FROM t",
        "SELECT SUM(a) OVER () FROM t WHERE f = 0",
        "sqlite",
        ignore_limit=True,
    )


def test_subquery_in_projection_is_not_rewritten() -> None:
    assert not structurally_equal(
        "SELECT (SELECT MAX(y) FROM b), SUM(CASE WHEN f = 0 THEN a END) FROM t",
        "SELECT (SELECT MAX(y) FROM b), SUM(a) FROM t WHERE f = 0",
        "sqlite",
        ignore_limit=True,
    )


def test_having_where_form_is_not_rewritten() -> None:
    assert not structurally_equal(
        "SELECT d, SUM(CASE WHEN f = 0 THEN a END) FROM t GROUP BY d",
        "SELECT d, SUM(a) FROM t WHERE f = 0 GROUP BY d HAVING SUM(a) > 1",
        "sqlite",
        ignore_limit=True,
    )
