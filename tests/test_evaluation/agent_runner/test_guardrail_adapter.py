"""Production guardrail adapter wraps product validate_read_only."""

import pytest

from eval.agent_runner.adapters import ProductionGuardrailAdapter, _map_error_code
from eval.evaluator.schemas import EvaluationConfig


async def test_accepts_select_with_literal_limit():
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("SELECT id FROM fact_orders LIMIT 10", "sqlite")
    assert out.accepted is True
    assert out.sql == "SELECT id FROM fact_orders LIMIT 10"
    assert out.effective_limit == 10
    assert out.effective_timeout_seconds == adapter._config.statement_timeout_seconds


async def test_accepts_select_without_limit_uses_default():
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("SELECT id FROM fact_orders", "sqlite")
    assert out.accepted is True
    assert out.effective_limit == EvaluationConfig().default_limit


async def test_rejects_delete_with_error_code():
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("DELETE FROM fact_orders", "sqlite")
    assert out.accepted is False
    assert out.error_code
    assert out.sql is None
    assert out.effective_limit is None
    assert out.effective_timeout_seconds is None


async def test_rejects_multi_statement():
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("SELECT 1; SELECT 2", "sqlite")
    assert out.accepted is False
    assert out.error_code == "MULTI_STATEMENT"


async def test_rejects_write_batch_as_non_select_statement():
    """A rejected batch containing a write keeps the golden precedence label."""
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("SELECT * FROM orders; DELETE FROM customers;", "mysql")
    assert out.accepted is False
    assert out.error_code == "NON_SELECT_STATEMENT"


async def test_rejects_cte_dml_with_golden_vocabulary():
    """The product's 'CTE containing DML' rejection maps to the golden NESTED_DML."""
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d", "postgresql")
    assert out.accepted is False
    assert out.error_code == "NESTED_DML"


async def test_rejects_select_into():
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("SELECT id INTO archive FROM fact_orders", "sqlite")
    assert out.accepted is False
    assert out.error_code == "SELECT_INTO_FORBIDDEN"


async def test_rejects_unparseable_sql_with_parse_error():
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("SELEC id FROM", "sqlite")
    assert out.accepted is False
    assert out.error_code == "SQL_PARSE_ERROR"


async def test_clamps_limit_above_maximum():
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("SELECT id FROM fact_orders LIMIT 5000", "sqlite")
    assert out.accepted is True
    assert out.effective_limit == adapter._config.maximum_limit


async def test_zero_limit_falls_back_to_default_limit():
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    out = await adapter.validate("SELECT id FROM fact_orders LIMIT 0", "sqlite")
    assert out.accepted is True
    assert out.effective_limit == adapter._config.default_limit


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        ("Invalid SQL: Invalid expression / Unexpected token", "SQL_PARSE_ERROR"),
        ("Multi-statement queries are not allowed", "MULTI_STATEMENT"),
        ("Only SELECT statements are allowed, got Delete", "NON_SELECT_STATEMENT"),
        ("SELECT INTO is not allowed", "SELECT_INTO_FORBIDDEN"),
        ("CTE containing DML is not allowed", "NESTED_DML"),
        ("DDL is not allowed", "DDL_FORBIDDEN"),
        ("totally unknown message", "UNSAFE_SQL"),
    ],
)
def test_map_error_code_matches_product_messages(message, expected_code):
    assert _map_error_code(message) == expected_code
