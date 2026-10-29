"""Tests for unified cross-database time bucket compilation and execution (Task 3)."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlglot
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    CanonicalRelationshipModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.services.query_compiler import (
    CompiledQuery,
    DimensionSelection,
    SemanticCompileError,
    SemanticQueryCompiler,
    SemanticQuerySpec,
)
from src.services.query_compiler_dialect import time_bucket_sql
from src.services.query_execution import _set_read_only, execute_compiled_query


@pytest.mark.parametrize(
    ("grain", "expected"),
    [
        ("day", """DATE_TRUNC('day', "orders"."created_at")"""),
        ("week", """DATE_TRUNC('week', "orders"."created_at")"""),
        ("month", """DATE_TRUNC('month', "orders"."created_at")"""),
        ("quarter", """DATE_TRUNC('quarter', "orders"."created_at")"""),
        ("year", """DATE_TRUNC('year', "orders"."created_at")"""),
    ],
)
def test_postgres_timestamp_without_timezone_keeps_wall_clock(grain: str, expected: str) -> None:
    """PostgreSQL TIMESTAMP without timezone uses DATE_TRUNC without AT TIME ZONE shift."""
    expr = time_bucket_sql('"orders"."created_at"', grain, "postgres", "TIMESTAMP")
    assert expr == expected
    sqlglot.parse_one(expr, read="postgres")


@pytest.mark.parametrize("data_type", ["TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE", "timestamptz"])
def test_postgres_timestamptz_normalizes_to_utc(data_type: str) -> None:
    """PostgreSQL TIMESTAMPTZ normalizes to UTC before DATE_TRUNC."""
    expr = time_bucket_sql('"orders"."created_at"', "week", "postgres", data_type)
    assert expr == """DATE_TRUNC('week', "orders"."created_at" AT TIME ZONE 'UTC')"""
    sqlglot.parse_one(expr, read="postgres")


@pytest.mark.parametrize(
    ("grain", "expected"),
    [
        ("day", "DATE_FORMAT(`orders`.`created_at`, '%Y-%m-%d')"),
        ("week", "DATE_FORMAT(`orders`.`created_at`, '%x-W%v')"),
        ("month", "DATE_FORMAT(`orders`.`created_at`, '%Y-%m')"),
        ("quarter", "CONCAT(YEAR(`orders`.`created_at`), '-Q', QUARTER(`orders`.`created_at`))"),
        ("year", "DATE_FORMAT(`orders`.`created_at`, '%Y')"),
    ],
)
def test_mysql_time_bucket_sql_formats(grain: str, expected: str) -> None:
    """MySQL renders ISO week '%x-W%v', month '%Y-%m', quarter 'YYYY-Q#', day, and year."""
    expr = time_bucket_sql("`orders`.`created_at`", grain, "mysql", "DATETIME")
    assert expr == expected
    sqlglot.parse_one(expr, read="mysql")


@pytest.mark.parametrize(
    ("grain", "expected_prefix"),
    [
        ("day", """strftime('%Y-%m-%d', "orders"."created_at")"""),
        ("week", """strftime('%Y', date("orders"."created_at", 'weekday 0', '-3 days')) || '-W'"""),
        ("month", """strftime('%Y-%m', "orders"."created_at")"""),
        ("quarter", """strftime('%Y', "orders"."created_at") || '-Q'"""),
        ("year", """strftime('%Y', "orders"."created_at")"""),
    ],
)
def test_sqlite_time_bucket_sql_formats(grain: str, expected_prefix: str) -> None:
    """SQLite renders standard label expressions for all five time grains."""
    expr = time_bucket_sql('"orders"."created_at"', grain, "sqlite", "TIMESTAMP")
    assert expr.startswith(expected_prefix)
    sqlglot.parse_one(expr, read="sqlite")


def test_time_bucket_sql_rejects_unsupported_grain() -> None:
    """Unsupported time grains fail closed with SemanticCompileError."""
    with pytest.raises(SemanticCompileError) as exc_info:
        time_bucket_sql('"orders"."created_at"', "hour", "postgres", "TIMESTAMP")
    assert exc_info.value.code == "INVALID_TIME_GRAIN"


def _create_temporal_sqlite_db(db_path: Path, rows: list[tuple[int, str, float]]) -> str:
    """Create a SQLite database with temporal test rows in orders and returns."""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, created_at TEXT, amount REAL)")
        conn.execute("CREATE TABLE returns (id INTEGER PRIMARY KEY, created_at TEXT, refund REAL)")
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?)", rows)
        conn.executemany("INSERT INTO returns VALUES (?, ?, ?)", rows)
        conn.commit()
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ts", "exp_day", "exp_week", "exp_month", "exp_quarter", "exp_year"),
    [
        ("2025-12-29", "2025-12-29", "2026-W01", "2025-12", "2025-Q4", "2025"),
        ("2025-12-31", "2025-12-31", "2026-W01", "2025-12", "2025-Q4", "2025"),
        ("2026-01-01", "2026-01-01", "2026-W01", "2026-01", "2026-Q1", "2026"),
        ("2021-01-01", "2021-01-01", "2020-W53", "2021-01", "2021-Q1", "2021"),
        ("2024-02-29", "2024-02-29", "2024-W09", "2024-02", "2024-Q1", "2024"),
        ("2026-01-01T01:30:00+07:00", "2025-12-31", "2026-W01", "2025-12", "2025-Q4", "2025"),
        ("2025-12-31T23:30:00-05:00", "2026-01-01", "2026-W01", "2026-01", "2026-Q1", "2026"),
        ("2026-05-15 14:20:00", "2026-05-15", "2026-W20", "2026-05", "2026-Q2", "2026"),
        ("2026-08-01", "2026-08-01", "2026-W31", "2026-08", "2026-Q3", "2026"),
    ],
)
async def test_sqlite_time_bucket_boundary_values(
    tmp_path: Path,
    ts: str,
    exp_day: str,
    exp_week: str,
    exp_month: str,
    exp_quarter: str,
    exp_year: str,
) -> None:
    """Verify year-end, ISO week cross-year, leap-year, quarter, and timezone-offset buckets on SQLite."""
    conn_url = _create_temporal_sqlite_db(tmp_path / "temporal.db", [(1, ts, 10.0)])
    cols = [
        f"{time_bucket_sql('created_at', g, 'sqlite', 'TIMESTAMP')} AS {g}"
        for g in ("day", "week", "month", "quarter", "year")
    ]
    query = CompiledQuery(sql=f"SELECT {', '.join(cols)} FROM orders", parameters={}, metadata={})  # noqa: S608
    res = await execute_compiled_query(conn_url, "sqlite", query)
    assert res.rows == [[exp_day, exp_week, exp_month, exp_quarter, exp_year]]


async def _seed_three_renderers_catalog(
    session: AsyncSession, db_type: str = "sqlite", created_data_type: str = "TIMESTAMP"
) -> dict[str, Any]:
    """Seed orders and returns tables with simple, single-plan, and bundle metrics."""
    db = SemanticDatabaseModel(
        created_by=1, display_name="temporal_db", db_type=db_type, conn_url_enc="encrypted", status="ready"
    )
    session.add(db)
    await session.flush()
    orders = SemanticTableModel(
        db_id=db.id, table_name="orders", physical_schema=None, business_name="Orders", primary_key_column="id"
    )
    returns = SemanticTableModel(
        db_id=db.id, table_name="returns", physical_schema=None, business_name="Returns", primary_key_column="id"
    )
    session.add_all([orders, returns])
    await session.flush()
    cols = await _seed_temporal_columns(session, db.id, orders, returns, created_data_type)
    metrics = await _seed_temporal_metrics(session, db.id, orders, returns, cols)
    await session.commit()
    return {"db": db, "cols": cols, "metrics": metrics}


async def _seed_temporal_columns(
    session: AsyncSession,
    db_id: int,
    orders: SemanticTableModel,
    returns: SemanticTableModel,
    created_data_type: str,
) -> dict[str, SemanticColumnModel]:
    """Create columns and a shared timestamp relationship for bundle queries."""
    ord_id = SemanticColumnModel(table_id=orders.id, column_name="id", data_type="INTEGER", business_name="Order ID")
    ord_ts = SemanticColumnModel(
        table_id=orders.id, column_name="created_at", data_type=created_data_type, business_name="Created At"
    )
    ord_amt = SemanticColumnModel(table_id=orders.id, column_name="amount", data_type="NUMERIC", business_name="Amount")
    ret_id = SemanticColumnModel(table_id=returns.id, column_name="id", data_type="INTEGER", business_name="Return ID")
    ret_ts = SemanticColumnModel(
        table_id=returns.id, column_name="created_at", data_type=created_data_type, business_name="Return Date"
    )
    ret_amt = SemanticColumnModel(
        table_id=returns.id, column_name="refund", data_type="NUMERIC", business_name="Refund"
    )
    session.add_all([ord_id, ord_ts, ord_amt, ret_id, ret_ts, ret_amt])
    await session.flush()
    session.add(
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=returns.id,
            to_entity_id=orders.id,
            relationship_type="many_to_one",
            join_condition="returns.created_at = orders.created_at",
            relationship_key="returns_orders_created_at",
            column_pairs=[{"from_column_id": ret_ts.id, "to_column_id": ord_ts.id}],
            validation_status="valid",
        )
    )
    await session.flush()
    return {
        "ord_id": ord_id,
        "ord_ts": ord_ts,
        "ord_amt": ord_amt,
        "ret_id": ret_id,
        "ret_ts": ret_ts,
        "ret_amt": ret_amt,
    }


def _new_metric_model(db_id: int, base_id: int, name: str, definition: dict[str, Any]) -> SemanticMetricModel:
    """Create an approved SemanticMetricModel instance."""
    return SemanticMetricModel(
        db_id=db_id,
        created_by=1,
        name=name,
        description="",
        sql_template="",
        formula="SUM",
        aggregation_type="SUM",
        base_entity_id=base_id,
        status="approved",
        definition=definition,
    )


async def _seed_temporal_metrics(
    session: AsyncSession,
    db_id: int,
    orders: SemanticTableModel,
    returns: SemanticTableModel,
    cols: dict[str, SemanticColumnModel],
) -> dict[str, SemanticMetricModel]:
    """Seed simple metric, single-plan metric, and second plan metric for bundle testing."""
    simple_def = _build_simple_metric_def("Simple Sales", orders.id, cols["ord_id"].id, cols["ord_amt"].id)
    plan_sales_def = _build_plan_metric_def(
        "Plan Sales", "orders", orders.id, "s_sales", [], cols["ord_ts"].id, "orders.amount"
    )
    plan_ref_def = _build_plan_metric_def(
        "Plan Refunds", "returns", returns.id, "s_refunds", ["orders"], cols["ord_ts"].id, "returns.refund"
    )
    m_simple = _new_metric_model(db_id, orders.id, "Simple Sales", simple_def)
    m_plan = _new_metric_model(db_id, orders.id, "Plan Sales", plan_sales_def)
    m_bundle = _new_metric_model(db_id, returns.id, "Plan Refunds", plan_ref_def)
    session.add_all([m_simple, m_plan, m_bundle])
    await session.flush()
    return {"simple": m_simple, "plan": m_plan, "refund_plan": m_bundle}


def _build_simple_metric_def(name: str, base_id: int, pk_id: int, amt_id: int) -> dict[str, Any]:
    """Build a canonical v2 simple metric definition for orders.amount."""
    return {
        "schema_version": 2,
        "metric": {
            "name": name,
            "base_entity": "orders",
            "base_entity_id": base_id,
            "grain": {"fields": ["id"], "column_ids": [pk_id]},
            "formula": {
                "function": "SUM",
                "expression": "amount",
                "expression_ast": {"kind": "column", "column_id": amt_id},
            },
            "filters": [],
            "status": "approved",
        },
    }


def _build_plan_metric_def(
    name: str, base: str, base_id: int, stage: str, joins: list[str], grp_col_id: int, agg_expr: str
) -> dict[str, Any]:
    """Build a canonical single-stage MetricQueryPlan definition grouped by orders.created_at."""
    return {
        "schema_version": 3,
        "metric": {
            "name": name,
            "base_entity": base,
            "base_entity_id": base_id,
            "formula": {"function": "COUNT", "expression": "*"},
            "query_plan": {
                "stages": [
                    {
                        "name": stage,
                        "base_entity": base,
                        "joins": joins,
                        "group_by": [{"name": "bucket", "expression": "orders.created_at", "column_id": grp_col_id}],
                        "aggregates": [{"name": "total", "function": "SUM", "expression": agg_expr}],
                    }
                ],
                "output_expression": f"{stage}.total",
            },
            "filters": [],
            "status": "approved",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("grain", ["day", "week", "month", "quarter", "year"])
async def test_three_renderers_produce_identical_time_buckets_on_sqlite(
    async_session: AsyncSession, tmp_path: Path, grain: str
) -> None:
    """Simple metric, single plan, and plan bundle produce identical bucket labels for every grain."""
    rows = [
        (1, "2025-12-29", 40.0),
        (2, "2026-01-01T01:30:00+07:00", 60.0),
        (3, "2024-02-29", 25.0),
    ]
    conn_url = _create_temporal_sqlite_db(tmp_path / f"unified_{grain}.db", rows)
    cat = await _seed_three_renderers_catalog(async_session, db_type="sqlite")
    db_id = cat["db"].id
    ts_col = cat["cols"]["ord_ts"]
    dim = [DimensionSelection(column_id=ts_col.id, time_grain=grain)]
    compiler = SemanticQueryCompiler(async_session)

    c_simple = await compiler.compile(
        db_id, SemanticQuerySpec(metric_ids=[cat["metrics"]["simple"].id], dimensions=dim)
    )
    c_plan = await compiler.compile(db_id, SemanticQuerySpec(metric_ids=[cat["metrics"]["plan"].id], dimensions=dim))
    c_bundle = await compiler.compile(
        db_id,
        SemanticQuerySpec(metric_ids=[cat["metrics"]["plan"].id, cat["metrics"]["refund_plan"].id], dimensions=dim),
    )

    r_simple = await execute_compiled_query(conn_url, "sqlite", c_simple)
    r_plan = await execute_compiled_query(conn_url, "sqlite", c_plan)
    r_bundle = await execute_compiled_query(conn_url, "sqlite", c_bundle)

    b_simple = {row[0]: row[1] for row in r_simple.rows}
    b_plan = {row[0]: row[1] for row in r_plan.rows}
    b_bundle = {row[0]: row[1] for row in r_bundle.rows}
    assert b_simple == b_plan == b_bundle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("db_type", "dialect", "col_type", "expected_snippet"),
    [
        ("postgresql", "postgres", "TIMESTAMPTZ", """DATE_TRUNC('week', "orders"."created_at" AT TIME ZONE 'UTC')"""),
        ("postgresql", "postgres", "TIMESTAMP", """DATE_TRUNC('week', "orders"."created_at")"""),
        ("mysql", "mysql", "DATETIME", "DATE_FORMAT(`orders`.`created_at`, '%x-W%v')"),
    ],
)
async def test_three_renderers_use_identical_dialect_sql_for_postgres_and_mysql(
    async_session: AsyncSession, db_type: str, dialect: str, col_type: str, expected_snippet: str
) -> None:
    """Simple metric, single plan, and plan bundle emit the same time_bucket_sql expression across dialects."""
    cat = await _seed_three_renderers_catalog(async_session, db_type=db_type, created_data_type=col_type)
    db_id = cat["db"].id
    dim = [DimensionSelection(column_id=cat["cols"]["ord_ts"].id, time_grain="week")]
    compiler = SemanticQueryCompiler(async_session)

    for metric_ids in (
        [cat["metrics"]["simple"].id],
        [cat["metrics"]["plan"].id],
        [cat["metrics"]["plan"].id, cat["metrics"]["refund_plan"].id],
    ):
        compiled = await compiler.compile(db_id, SemanticQuerySpec(metric_ids=metric_ids, dimensions=dim))
        assert expected_snippet in compiled.sql
        sqlglot.parse_one(compiled.sql, read=dialect)


def _build_multi_stage_def(base_id: int, ts_col_id: int) -> dict[str, Any]:
    """Build a two-stage MetricQueryPlan definition where s2 groups by s1.bucket."""
    stages = [
        {
            "name": "s1",
            "base_entity": "orders",
            "group_by": [{"name": "bucket", "expression": "orders.created_at", "column_id": ts_col_id}],
            "aggregates": [{"name": "sub_total", "function": "SUM", "expression": "orders.amount"}],
        },
        {
            "name": "s2",
            "source_stage": "s1",
            "group_by": [{"name": "bucket", "expression": "s1.bucket"}],
            "aggregates": [{"name": "grand_total", "function": "SUM", "expression": "s1.sub_total"}],
        },
    ]
    return {
        "schema_version": 3,
        "metric": {
            "name": "Multi Stage Weekly",
            "base_entity": "orders",
            "base_entity_id": base_id,
            "formula": {"function": "COUNT", "expression": "*"},
            "query_plan": {"stages": stages, "output_expression": "s2.grand_total"},
            "filters": [],
            "status": "approved",
        },
    }


@pytest.mark.asyncio
async def test_multi_stage_plan_does_not_double_bucket_derived_stage(
    async_session: AsyncSession, tmp_path: Path
) -> None:
    """A derived stage referencing a parent stage's bucketed column must not apply time_bucket_sql twice."""
    conn_url = _create_temporal_sqlite_db(tmp_path / "multistage_time.db", [(1, "2025-12-29", 100.0)])
    cat = await _seed_three_renderers_catalog(async_session, db_type="sqlite")
    ts_col = cat["cols"]["ord_ts"]
    orders = await async_session.get(SemanticTableModel, ts_col.table_id)
    assert orders is not None
    metric = _new_metric_model(
        cat["db"].id, orders.id, "Multi Stage Weekly", _build_multi_stage_def(orders.id, ts_col.id)
    )
    async_session.add(metric)
    await async_session.commit()

    spec = SemanticQuerySpec(
        metric_ids=[metric.id], dimensions=[DimensionSelection(column_id=ts_col.id, time_grain="week")]
    )
    compiled = await SemanticQueryCompiler(async_session).compile(cat["db"].id, spec)
    result = await execute_compiled_query(conn_url, "sqlite", compiled)
    assert result.rows == [["2026-W01", 100.0]]


@pytest.mark.asyncio
async def test_query_execution_sets_utc_session_timezone_for_postgres_and_mysql() -> None:
    """_set_read_only configures UTC session timezone on PostgreSQL and MySQL connections."""
    pg_conn = MagicMock()
    pg_conn.execute = AsyncMock()
    await _set_read_only(pg_conn, "postgres", 15)
    pg_sqls = [str(call.args[0]) for call in pg_conn.execute.call_args_list]
    assert any("TIME ZONE 'UTC'" in s for s in pg_sqls)

    my_conn = MagicMock()
    my_conn.execute = AsyncMock()
    await _set_read_only(my_conn, "mysql", 15)
    my_sqls = [str(call.args[0]) for call in my_conn.execute.call_args_list]
    assert any("time_zone = '+00:00'" in s for s in my_sqls)
