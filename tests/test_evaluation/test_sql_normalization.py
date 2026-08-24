"""Tests for SQL AST canonicalization and safety validation."""

import pytest

from eval.evaluator.sql_normalization import SqlValidationError, normalize_sql, structurally_equal


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
