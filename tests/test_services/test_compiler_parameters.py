"""Unit and integration tests for column-type-driven filter parameter binding (Task 2)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.metric_definition import MetricPlanFilter, MetricPlanStage, MetricQueryPlan
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.services.query_compiler import CompiledQuery, SemanticQueryCompiler
from src.services.query_compiler_plan import _plan_filter, compile_plan_sql
from src.services.query_compiler_sql import coerce_filter_value
from src.services.query_execution import _normalize_parameters, execute_compiled_query
from src.services.semantic_compile_error import SemanticCompileError


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql", "mysql"])
@pytest.mark.parametrize("data_type", ["TEXT", "VARCHAR(50)", "CHAR(10)", "NVARCHAR(32)"])
@pytest.mark.parametrize("raw_value", ["2026-01-01", "0012", "2026-01-01T10:20:30"])
def test_coerce_filter_value_preserves_text_strings_verbatim(dialect: str, data_type: str, raw_value: str) -> None:
    """Text columns must preserve date-shaped and zero-padded strings as str."""
    coerced = coerce_filter_value(raw_value, data_type, dialect)
    assert type(coerced) is str
    assert coerced == raw_value


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql", "mysql"])
@pytest.mark.parametrize("data_type", ["INTEGER", "INT", "BIGINT", "SMALLINT"])
def test_coerce_filter_value_integer_columns(dialect: str, data_type: str) -> None:
    """Integer columns coerce valid integers and reject booleans/floats/non-integers."""
    assert coerce_filter_value("42", data_type, dialect) == 42
    assert type(coerce_filter_value("42", data_type, dialect)) is int
    assert coerce_filter_value("-7", data_type, dialect) == -7
    assert coerce_filter_value(0, data_type, dialect) == 0

    for invalid in ["abc", "12.5", True, False, 12.5, None]:
        with pytest.raises(SemanticCompileError) as exc_info:
            coerce_filter_value(invalid, data_type, dialect)
        assert exc_info.value.code == "INVALID_FILTER_VALUE"


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql", "mysql"])
@pytest.mark.parametrize("data_type", ["DECIMAL(10,2)", "NUMERIC(12,4)", "DECIMAL", "NUMERIC"])
def test_coerce_filter_value_decimal_columns(dialect: str, data_type: str) -> None:
    """Decimal/numeric columns coerce to Decimal and reject invalid values."""
    coerced = coerce_filter_value("19.95", data_type, dialect)
    assert isinstance(coerced, Decimal)
    assert coerced == Decimal("19.95")
    assert coerce_filter_value(10, data_type, dialect) == Decimal("10")
    assert coerce_filter_value(Decimal("0.25"), data_type, dialect) == Decimal("0.25")

    for invalid in ["not-a-decimal", "NaN", "Infinity", "-Infinity", True, False, None]:
        with pytest.raises(SemanticCompileError) as exc_info:
            coerce_filter_value(invalid, data_type, dialect)
        assert exc_info.value.code == "INVALID_FILTER_VALUE"


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql", "mysql"])
@pytest.mark.parametrize("data_type", ["BOOLEAN", "BOOL"])
def test_coerce_filter_value_boolean_columns(dialect: str, data_type: str) -> None:
    """Boolean columns coerce boolean representations to bool and reject invalid values."""
    assert coerce_filter_value(True, data_type, dialect) is True
    assert coerce_filter_value(False, data_type, dialect) is False
    assert coerce_filter_value("true", data_type, dialect) is True
    assert coerce_filter_value("FALSE", data_type, dialect) is False
    assert coerce_filter_value("1", data_type, dialect) is True
    assert coerce_filter_value("0", data_type, dialect) is False
    assert coerce_filter_value(1, data_type, dialect) is True
    assert coerce_filter_value(0, data_type, dialect) is False

    for invalid in ["yes-maybe", "2", 2, -1, None]:
        with pytest.raises(SemanticCompileError) as exc_info:
            coerce_filter_value(invalid, data_type, dialect)
        assert exc_info.value.code == "INVALID_FILTER_VALUE"


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql", "mysql"])
def test_coerce_filter_value_date_and_datetime_columns(dialect: str) -> None:
    """Date and datetime/timestamp columns coerce valid ISO strings and reject invalid ones."""
    coerced_date = coerce_filter_value("2026-01-15", "DATE", dialect)
    assert type(coerced_date) is date
    assert coerced_date == date(2026, 1, 15)

    coerced_dt = coerce_filter_value("2026-01-15T08:30:00", "TIMESTAMP", dialect)
    assert isinstance(coerced_dt, datetime)
    assert coerced_dt == datetime(2026, 1, 15, 8, 30, 0)

    coerced_ts_date = coerce_filter_value("2026-01-15", "DATETIME", dialect)
    assert coerced_ts_date == date(2026, 1, 15)

    for data_type, invalid in [
        ("DATE", "not-a-date"),
        ("DATE", "2026-13-40"),
        ("DATE", 20260115),
        ("TIMESTAMP", "not-a-timestamp"),
        ("DATETIME", 12345),
    ]:
        with pytest.raises(SemanticCompileError) as exc_info:
            coerce_filter_value(invalid, data_type, dialect)
        assert exc_info.value.code == "INVALID_FILTER_VALUE"


def test_executor_normalize_parameters_does_not_guess_dates_from_strings() -> None:
    """Query execution parameter normalizer must not convert date-looking strings to date."""
    params = {"p_text_date": "2026-01-01", "p_code": "0012", "p_real_date": date(2026, 1, 1)}
    normalized = _normalize_parameters(params)
    assert type(normalized["p_text_date"]) is str
    assert normalized["p_text_date"] == "2026-01-01"
    assert normalized["p_code"] == "0012"
    assert normalized["p_real_date"] == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_sqlite_decimal_parameter_preserves_decimal_digits(tmp_path) -> None:
    value = Decimal("12345678901234567890.123456789")
    compiled = CompiledQuery(sql="SELECT CAST(:value AS TEXT) LIMIT 100", parameters={"value": value})
    result = await execute_compiled_query(f"sqlite+aiosqlite:///{tmp_path / 'decimal.db'}", "sqlite", compiled)
    assert result.rows == [[str(value)]]


@pytest.mark.asyncio
async def test_sqlite_filter_on_aggregate_compares_decimals_numerically(tmp_path) -> None:
    source = MetricPlanStage.model_validate(
        {
            "name": "source",
            "base_entity": "orders",
            "aggregates": [{"name": "value", "function": "SUM", "expression": "amount"}],
        }
    )
    stage = MetricPlanStage.model_validate(
        {
            "name": "summary",
            "source_stage": "source",
            "aggregates": [{"name": "total", "function": "SUM", "expression": "value"}],
        }
    )
    params = {}
    condition = _plan_filter(
        MetricPlanFilter(field="source.value", operator="gte", value="60.0"),
        stage,
        None,
        {},
        {},
        {"value"},
        "sqlite",
        params,
        "p",
        stage_map={"source": source},
    )
    compiled = CompiledQuery(
        sql=f"SELECT COUNT(*) FROM (SELECT 100 AS value) WHERE {condition} LIMIT 100",  # noqa: S608
        parameters=params,
    )
    result = await execute_compiled_query(f"sqlite+aiosqlite:///{tmp_path / 'filter.db'}", "sqlite", compiled)
    assert result.rows == [[1]]


@pytest.mark.asyncio
async def test_sqlite_numeric_cannot_distinguish_high_precision_decimals(tmp_path) -> None:
    compiled = CompiledQuery(
        sql="SELECT CAST(:a AS NUMERIC) = CAST(:b AS NUMERIC) LIMIT 100",
        parameters={"a": Decimal("100000000000000000000.5"), "b": Decimal("100000000000000000001.5")},
    )
    result = await execute_compiled_query(f"sqlite+aiosqlite:///{tmp_path / 'precision.db'}", "sqlite", compiled)
    assert result.rows == [[1]]


async def _add_test_metric(
    session: AsyncSession, db_id: int, table_id: int, pk_id: int, name: str, fn: str, body: dict[str, object]
) -> SemanticMetricModel:
    """Persist an approved SemanticMetricModel with v2/v3 definition."""
    ver = 3 if "query_plan" in body else 2
    defn = {
        "schema_version": ver,
        "metric": {"name": name, "status": "approved", "grain": {"fields": ["id"], "column_ids": [pk_id]}, **body},
    }
    metric = SemanticMetricModel(
        db_id=db_id,
        created_by=1,
        name=name,
        description="",
        sql_template="",
        formula=fn,
        aggregation_type=fn,
        base_entity_id=table_id,
        status="approved",
        definition=defn,
    )
    session.add(metric)
    await session.flush()
    return metric


async def _seed_parameter_test_schema(session: AsyncSession) -> dict[str, int]:
    """Seed an orders table with diverse column types and both simple and plan metrics."""
    db = SemanticDatabaseModel(
        created_by=1, display_name="ParamDB", db_type="sqlite", conn_url_enc="encrypted", status="draft"
    )
    session.add(db)
    await session.flush()
    orders = SemanticTableModel(
        db_id=db.id, table_name="orders", business_name="Đơn hàng", description="", primary_key_column="id"
    )
    session.add(orders)
    await session.flush()
    cols = {
        name: SemanticColumnModel(
            table_id=orders.id, column_name=name, data_type=dtype, business_name=name, is_time_dimension=is_time
        )
        for name, dtype, is_time in (
            ("id", "INTEGER", False),
            ("order_code", "VARCHAR(32)", False),
            ("batch_tag", "TEXT", False),
            ("amount", "DECIMAL(10,2)", False),
            ("is_paid", "BOOLEAN", False),
            ("order_date", "DATE", True),
            ("created_at", "TIMESTAMP", True),
        )
    }
    session.add_all(cols.values())
    await session.flush()
    return await _seed_parameter_test_metrics(session, db.id, orders.id, cols)


async def _seed_parameter_test_metrics(
    session: AsyncSession, db_id: int, orders_id: int, cols: dict[str, SemanticColumnModel]
) -> dict[str, int]:
    """Seed simple and query_plan metrics on the orders test schema."""
    simple_metric = await _add_test_metric(
        session, db_id, orders_id, cols["id"].id, "paid_revenue", "SUM", _simple_metric_body(cols)
    )
    plan_a = await _add_test_metric(
        session, db_id, orders_id, cols["id"].id, "high_value_orders_a", "COUNT", _plan_a_body(cols)
    )
    plan_b = await _add_test_metric(
        session, db_id, orders_id, cols["id"].id, "high_value_orders_b", "COUNT", _plan_b_body(cols)
    )
    await session.commit()
    return {
        "db_id": db_id,
        "col_id": cols["id"].id,
        "col_code": cols["order_code"].id,
        "col_batch": cols["batch_tag"].id,
        "col_amount": cols["amount"].id,
        "col_is_paid": cols["is_paid"].id,
        "col_order_date": cols["order_date"].id,
        "col_created_at": cols["created_at"].id,
        "simple_metric_id": simple_metric.id,
        "plan_metric_a_id": plan_a.id,
        "plan_metric_b_id": plan_b.id,
    }


def _simple_metric_body(cols: dict[str, SemanticColumnModel]) -> dict[str, object]:
    """Build simple metric definition payload with text and code filters."""
    return {
        "base_entity": "orders",
        "formula": {
            "function": "SUM",
            "expression": "amount",
            "expression_ast": {"kind": "column", "column_id": cols["amount"].id},
        },
        "filters": [
            {"field": "batch_tag", "column_id": cols["batch_tag"].id, "operator": "eq", "value": "2026-01-01"},
            {"field": "order_code", "column_id": cols["order_code"].id, "operator": "eq", "value": "0012"},
        ],
    }


def _plan_a_body(cols: dict[str, SemanticColumnModel]) -> dict[str, object]:
    """Build plan metric A definition payload."""
    return _plan_metric_body(
        "stage_a",
        cols["order_code"].id,
        [
            {"field": "orders.amount", "column_id": cols["amount"].id, "operator": "gte", "value": "100.50"},
            {"field": "orders.order_code", "column_id": cols["order_code"].id, "operator": "eq", "value": "0012"},
        ],
    )


def _plan_b_body(cols: dict[str, SemanticColumnModel]) -> dict[str, object]:
    """Build plan metric B definition payload."""
    return _plan_metric_body(
        "stage_b",
        cols["order_code"].id,
        [{"field": "orders.batch_tag", "column_id": cols["batch_tag"].id, "operator": "eq", "value": "2026-01-01"}],
    )


def _plan_metric_body(stage_name: str, group_col_id: int, filters: list[dict[str, object]]) -> dict[str, object]:
    """Build a single-stage query_plan body with custom stage filters."""
    return {
        "base_entity": "orders",
        "formula": {"function": "COUNT", "expression": "*"},
        "filters": [],
        "query_plan": {
            "stages": [
                {
                    "name": stage_name,
                    "base_entity": "orders",
                    "group_by": [{"name": "order_code", "expression": "orders.order_code", "column_id": group_col_id}],
                    "aggregates": [{"name": "order_count", "function": "COUNT", "expression": "orders.id"}],
                    "filters": filters,
                }
            ],
            "output_expression": f"{stage_name}.order_count",
        },
    }


async def _create_physical_orders_table(session: AsyncSession) -> None:
    """Create and populate the physical orders table in SQLite for execution checks."""
    await session.execute(
        text(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, order_code TEXT, "
            "batch_tag TEXT, amount NUMERIC, is_paid BOOLEAN, order_date DATE, created_at TIMESTAMP)"
        )
    )
    await session.execute(
        text(
            "INSERT INTO orders VALUES "
            "(1, 10, '0012', '2026-01-01', 150.25, 1, '2026-01-15', '2026-01-15 09:00:00'), "
            "(2, 10, '12', '2026-01-01', 999.00, 1, '2026-01-15', '2026-01-15 09:00:00')"
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_simple_and_runtime_filters_coerce_by_column_type(async_session: AsyncSession) -> None:
    """Simple metric filters and runtime filters must bind according to column metadata."""
    ids = await _seed_parameter_test_schema(async_session)
    await _create_physical_orders_table(async_session)
    compiled = await SemanticQueryCompiler(async_session).compile(
        ids["db_id"],
        SemanticQuerySpec(
            metric_ids=[ids["simple_metric_id"]],
            filters=[
                SemanticQueryFilter(column_id=ids["col_amount"], operator="gte", value="100.50"),
                SemanticQueryFilter(column_id=ids["col_is_paid"], operator="eq", value="true"),
                SemanticQueryFilter(column_id=ids["col_order_date"], operator="eq", value="2026-01-15"),
            ],
        ),
    )
    assert compiled.parameters["fixed_0"] == "2026-01-01" and type(compiled.parameters["fixed_0"]) is str
    assert compiled.parameters["fixed_1"] == "0012" and type(compiled.parameters["fixed_1"]) is str
    assert compiled.parameters["runtime_2"] == Decimal("100.50")
    assert compiled.parameters["runtime_3"] is True
    assert compiled.parameters["runtime_4"] == date(2026, 1, 15)
    row = (await async_session.execute(text(compiled.sql), _normalize_parameters(compiled.parameters, "sqlite"))).one()
    assert float(row[0]) == pytest.approx(150.25)


@pytest.mark.asyncio
async def test_in_and_not_in_validate_every_list_element(async_session: AsyncSession) -> None:
    """IN and NOT IN filters must coerce every list element and fail on any invalid element."""
    ids = await _seed_parameter_test_schema(async_session)
    compiler = SemanticQueryCompiler(async_session)

    compiled = await compiler.compile(
        ids["db_id"],
        SemanticQuerySpec(
            metric_ids=[ids["simple_metric_id"]],
            filters=[
                SemanticQueryFilter(column_id=ids["col_id"], operator="in", value=["1", 2, "3"]),
            ],
        ),
    )
    assert compiled.parameters["runtime_2"] == 1
    assert compiled.parameters["runtime_3"] == 2
    assert compiled.parameters["runtime_4"] == 3

    for bad_in_value in [["1", "bad-int"], [], "not-a-list"]:
        with pytest.raises(SemanticCompileError) as exc_info:
            await compiler.compile(
                ids["db_id"],
                SemanticQuerySpec(
                    metric_ids=[ids["simple_metric_id"]],
                    filters=[
                        SemanticQueryFilter(column_id=ids["col_id"], operator="in", value=bad_in_value),
                    ],
                ),
            )
        assert exc_info.value.code == "INVALID_FILTER_VALUE"


@pytest.mark.asyncio
async def test_plan_and_bundle_isolate_parameters_and_coerce_by_column_type(
    async_session: AsyncSession,
) -> None:
    """Query plans and multi-metric plan bundles must isolate parameter names per metric and coerce types."""
    ids = await _seed_parameter_test_schema(async_session)
    compiler = SemanticQueryCompiler(async_session)

    compiled = await compiler.compile(
        ids["db_id"],
        SemanticQuerySpec(
            metric_ids=[ids["plan_metric_a_id"], ids["plan_metric_b_id"]],
            dimensions=[DimensionSelection(column_id=ids["col_code"])],
        ),
    )

    prefixes = {name.split("_plan_", maxsplit=1)[0] for name in compiled.parameters}
    assert prefixes == {f"metric_{ids['plan_metric_a_id']}", f"metric_{ids['plan_metric_b_id']}"}
    assert Decimal("100.50") in compiled.parameters.values()
    assert "0012" in compiled.parameters.values()
    assert "2026-01-01" in compiled.parameters.values()
    assert all(not isinstance(val, date) for val in compiled.parameters.values())


def _build_in_filter_plan(values: list[object]) -> MetricQueryPlan:
    """Build a MetricQueryPlan with an IN filter on orders.id."""
    return MetricQueryPlan.model_validate(
        {
            "stages": [
                {
                    "name": "s1",
                    "base_entity": "orders",
                    "aggregates": [{"name": "cnt", "function": "COUNT", "expression": "orders.id"}],
                    "filters": [{"field": "orders.id", "operator": "in", "value": values}],
                }
            ],
            "output_expression": "s1.cnt",
        }
    )


def test_compile_plan_sql_validates_in_filter_elements_by_column_type() -> None:
    """Direct plan compilation must coerce IN elements and reject invalid values."""
    tables = {"orders": SemanticTableModel(id=1, db_id=1, table_name="orders", business_name="Đơn")}
    columns = {"orders": {"id": ("id", 1, "INTEGER"), "order_code": ("order_code", 2, "VARCHAR(20)")}}
    params: dict[str, object] = {}
    compile_plan_sql(_build_in_filter_plan(["10", 20]), 1, "sqlite", tables, columns, {}, [], {}, [], 100, params)
    assert list(params.values()) == [10, 20]
    with pytest.raises(SemanticCompileError) as exc_info:
        compile_plan_sql(_build_in_filter_plan(["10", "oops"]), 1, "sqlite", tables, columns, {}, [], {}, [], 100, {})
    assert exc_info.value.code == "INVALID_FILTER_VALUE"


@pytest.mark.asyncio
async def test_raw_filter_values_never_leak_into_trace_or_error_diagnostics(
    async_session: AsyncSession,
) -> None:
    """Compilation traces and error diagnostics must never expose raw filter values."""
    ids = await _seed_parameter_test_schema(async_session)
    compiler = SemanticQueryCompiler(async_session)
    secret_literal = "TOP_SECRET_FILTER_TOKEN_98765"
    compiled = await compiler.compile(
        ids["db_id"],
        SemanticQuerySpec(
            metric_ids=[ids["simple_metric_id"]],
            filters=[SemanticQueryFilter(column_id=ids["col_code"], operator="eq", value=secret_literal)],
        ),
    )
    assert secret_literal not in compiled.sql and secret_literal not in str(compiled.metadata)
    bad_secret = "SECRET_BAD_INT_VALUE_54321"
    with pytest.raises(SemanticCompileError) as exc_info:
        await compiler.compile(
            ids["db_id"],
            SemanticQuerySpec(
                metric_ids=[ids["simple_metric_id"]],
                filters=[SemanticQueryFilter(column_id=ids["col_id"], operator="eq", value=bad_secret)],
            ),
        )
    assert exc_info.value.code == "INVALID_FILTER_VALUE"
    assert bad_secret not in str(exc_info.value) and bad_secret not in str(exc_info.value.context)
    await _assert_column_ref_filter_does_not_leak(async_session, compiler, ids)


async def _assert_column_ref_filter_does_not_leak(
    session: AsyncSession, compiler: SemanticQueryCompiler, ids: dict[str, int]
) -> None:
    """Verify metric filter column-reference rejection omits raw value from error context."""
    col_ref_secret = "orders.secret_column"
    body = {
        "base_entity": "orders",
        "formula": {
            "function": "SUM",
            "expression": "amount",
            "expression_ast": {"kind": "column", "column_id": ids["col_amount"]},
        },
        "filters": [{"field": "order_code", "column_id": ids["col_code"], "operator": "eq", "value": col_ref_secret}],
    }
    bad_metric = await _add_test_metric(session, ids["db_id"], 1, ids["col_id"], "bad_ref_metric", "SUM", body)
    await session.flush()
    with pytest.raises(SemanticCompileError) as exc_info_ref:
        await compiler.compile(ids["db_id"], SemanticQuerySpec(metric_ids=[bad_metric.id]))
    assert exc_info_ref.value.code == "INVALID_FILTER_VALUE"
    assert col_ref_secret not in str(exc_info_ref.value)
    assert col_ref_secret not in str(exc_info_ref.value.context)
