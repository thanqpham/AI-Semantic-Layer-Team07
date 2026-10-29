"""Cross-database semantic compiler baseline and gap coverage matrix."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import sqlglot
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    CanonicalRelationshipModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.services.query_compiler import SemanticQueryCompiler
from src.services.query_execution import execute_compiled_query
from src.services.semantic_compile_error import SemanticCompileError

_COMMERCE_SQL: tuple[str, ...] = (
    'CREATE TABLE "customers" ("id" INTEGER PRIMARY KEY, "region" TEXT)',
    'CREATE TABLE "orders" ("id" INTEGER PRIMARY KEY, "customer_id" INTEGER, "amount" NUMERIC, "status" TEXT, "order_code" TEXT, "created_at" DATE)',
    'CREATE TABLE "order_items" ("id" INTEGER PRIMARY KEY, "order_id" INTEGER, "product_name" TEXT, "line_amount" NUMERIC)',
    'CREATE TABLE "payments" ("id" INTEGER PRIMARY KEY, "order_id" INTEGER, "method" TEXT, "paid_amount" NUMERIC)',
    'CREATE TABLE "returns" ("id" INTEGER PRIMARY KEY, "customer_id" INTEGER, "refund_amount" NUMERIC)',
    """INSERT INTO "customers" VALUES (1, 'north'), (2, 'south'), (3, NULL)""",
    """INSERT INTO "orders" VALUES (1, 1, 100, 'completed', '2026-01-01', '2026-01-01')""",
    """INSERT INTO "order_items" VALUES (1, 1, 'Widget', 40), (2, 1, 'Gadget', 60)""",
    """INSERT INTO "payments" VALUES (1, 1, 'card', 30), (2, 1, 'card', 30), (3, 1, 'wallet', 40)""",
    """INSERT INTO "returns" VALUES (1, 1, 25), (2, 3, 10)""",
)

_COLUMN_SPECS: tuple[tuple[str, str, str, str, bool, bool], ...] = (
    ("cust_id", "customers", "id", "INTEGER", True, False),
    ("cust_region", "customers", "region", "TEXT", False, False),
    ("ord_id", "orders", "id", "INTEGER", True, False),
    ("ord_cust_id", "orders", "customer_id", "INTEGER", False, False),
    ("ord_amount", "orders", "amount", "NUMERIC", False, False),
    ("ord_status", "orders", "status", "TEXT", False, False),
    ("ord_code", "orders", "order_code", "TEXT", False, False),
    ("ord_created", "orders", "created_at", "DATE", False, True),
    ("item_id", "order_items", "id", "INTEGER", True, False),
    ("item_ord_id", "order_items", "order_id", "INTEGER", False, False),
    ("item_product", "order_items", "product_name", "TEXT", False, False),
    ("item_amount", "order_items", "line_amount", "NUMERIC", False, False),
    ("pay_id", "payments", "id", "INTEGER", True, False),
    ("pay_ord_id", "payments", "order_id", "INTEGER", False, False),
    ("pay_method", "payments", "method", "TEXT", False, False),
    ("ret_id", "returns", "id", "INTEGER", True, False),
    ("ret_cust_id", "returns", "customer_id", "INTEGER", False, False),
    ("ret_amount", "returns", "refund_amount", "NUMERIC", False, False),
)


def _create_commerce_sqlite_db(db_path: Path, extra_sql: tuple[str, ...] = ()) -> str:
    """Create a physical SQLite database with the 1-order, 2-items, 3-payments fixture."""
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        for statement in (*_COMMERCE_SQL, *extra_sql):
            connection.execute(text(statement))
    engine.dispose()
    return f"sqlite+aiosqlite:///{db_path}"


async def _seed_tables_and_columns(session: AsyncSession, db_id: int) -> dict[str, Any]:
    """Seed canonical tables and columns for customers, orders, order_items, payments, and returns."""
    tables = {
        name: SemanticTableModel(
            db_id=db_id, table_name=name, business_name=name.title(), description="", primary_key_column="id"
        )
        for name in ("customers", "orders", "order_items", "payments", "returns")
    }
    session.add_all(tables.values())
    await session.flush()
    cols = _build_column_models(tables)
    session.add_all(cols.values())
    await session.flush()
    return {"tables": tables, "cols": cols}


def _build_column_models(tables: dict[str, SemanticTableModel]) -> dict[str, SemanticColumnModel]:
    """Construct canonical column models for the cross-database commerce fixture."""
    return {
        key: SemanticColumnModel(
            table_id=tables[tbl].id,
            column_name=col,
            data_type=dtype,
            business_name=key,
            is_primary_key=is_pk,
            is_time_dimension=is_time,
        )
        for key, tbl, col, dtype, is_pk, is_time in _COLUMN_SPECS
    }


async def _seed_relationships(session: AsyncSession, db_id: int, meta: dict[str, Any]) -> None:
    """Seed canonical many-to-one and one-to-many relationships for the commerce schema."""
    t, c = meta["tables"], meta["cols"]
    rel_specs = (
        ("orders_cust", t["orders"], t["customers"], "many_to_one", c["ord_cust_id"], c["cust_id"]),
        ("returns_cust", t["returns"], t["customers"], "many_to_one", c["ret_cust_id"], c["cust_id"]),
        ("orders_items_1n", t["orders"], t["order_items"], "one_to_many", c["ord_id"], c["item_ord_id"]),
        ("orders_payments_1n", t["orders"], t["payments"], "one_to_many", c["ord_id"], c["pay_ord_id"]),
    )
    session.add_all(
        [
            CanonicalRelationshipModel(
                connection_id=db_id,
                from_entity_id=src.id,
                to_entity_id=dst.id,
                relationship_type=rel_type,
                join_condition=f"{src.table_name}.{fk.column_name} = {dst.table_name}.{pk.column_name}",
                relationship_key=key,
                column_pairs=[{"from_column_id": fk.id, "to_column_id": pk.id}],
                validation_status="valid",
            )
            for key, src, dst, rel_type, fk, pk in rel_specs
        ]
    )
    await session.flush()


async def _add_metric(
    session: AsyncSession, db_id: int, base: SemanticTableModel, pk_id: int, name: str, fn: str, body: dict[str, Any]
) -> SemanticMetricModel:
    """Persist an approved SemanticMetricModel with a canonical v2/v3 definition."""
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
        base_entity_id=base.id,
        status="approved",
        definition=defn,
    )
    session.add(metric)
    await session.flush()
    return metric


async def _seed_commerce_catalog(session: AsyncSession) -> dict[str, Any]:
    """Create the full canonical commerce catalog and return model references."""
    semantic_db = SemanticDatabaseModel(
        created_by=1, display_name="CrossDB", db_type="sqlite", conn_url_enc="encrypted", status="draft"
    )
    session.add(semantic_db)
    await session.flush()
    meta = await _seed_tables_and_columns(session, semantic_db.id)
    await _seed_relationships(session, semantic_db.id, meta)
    metrics = await _seed_baseline_metrics(session, semantic_db.id, meta)
    await session.commit()
    return {"db": semantic_db, "tables": meta["tables"], "cols": meta["cols"], "metrics": metrics}


def _simple_body(
    base: str, fn: str, expr: str, col: SemanticColumnModel, filters: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a canonical simple metric body dictionary."""
    ast = {"kind": "column", "column_id": col.id}
    return {
        "base_entity": base,
        "formula": {"function": fn, "expression": expr, "expression_ast": ast},
        "filters": filters,
    }


def _ratio_body(
    num_col: SemanticColumnModel, den_col: SemanticColumnModel, canc_flt: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a canonical zero-denominator ratio metric body dictionary."""
    num = {"function": "SUM", "expression": "amount", "expression_ast": {"kind": "column", "column_id": num_col.id}}
    den = {
        "function": "COUNT",
        "expression": "id",
        "expression_ast": {"kind": "column", "column_id": den_col.id},
        "filters": canc_flt,
    }
    return {"base_entity": "orders", "formula": {**num, "ratio": {"numerator": num, "denominator": den}}, "filters": []}


def _single_stage_plan_body(stage: str, base: str, group_col: SemanticColumnModel, expr: str) -> dict[str, Any]:
    """Build a canonical single-stage query_plan metric body dictionary."""
    grp = [{"name": "region", "expression": "customers.region", "column_id": group_col.id}]
    agg = [{"name": "total", "function": "SUM", "expression": expr}]
    plan = {
        "stages": [{"name": stage, "base_entity": base, "joins": ["customers"], "group_by": grp, "aggregates": agg}],
        "output_expression": f"{stage}.total",
    }
    return {"base_entity": base, "formula": {"function": "COUNT", "expression": "*"}, "query_plan": plan, "filters": []}


async def _seed_baseline_metrics(
    session: AsyncSession, db_id: int, meta: dict[str, Any]
) -> dict[str, SemanticMetricModel]:
    """Seed simple, conditional, ratio, multi-stage, and multi-fact metrics."""
    t, c = meta["tables"], meta["cols"]
    comp_flt = [{"field": "status", "column_id": c["ord_status"].id, "operator": "eq", "value": "completed"}]
    canc_flt = [{"field": "status", "column_id": c["ord_status"].id, "operator": "eq", "value": "cancelled"}]
    rev_body = _simple_body("orders", "SUM", "amount", c["ord_amount"], comp_flt)
    canc_body = _simple_body("orders", "COUNT", "id", c["ord_id"], canc_flt)
    ref_body = _simple_body("returns", "SUM", "refund_amount", c["ret_amount"], [])
    rev = await _add_metric(session, db_id, t["orders"], c["ord_id"].id, "Total Revenue", "SUM", rev_body)
    cancelled = await _add_metric(session, db_id, t["orders"], c["ord_id"].id, "Cancelled Orders", "COUNT", canc_body)
    refunds = await _add_metric(session, db_id, t["returns"], c["ret_id"].id, "Simple Refunds", "SUM", ref_body)
    plans = await _seed_ratio_and_plan_metrics(session, db_id, meta, canc_flt)
    return {"revenue": rev, "cancelled": cancelled, "refunds_simple": refunds, **plans}


async def _seed_ratio_and_plan_metrics(
    session: AsyncSession, db_id: int, meta: dict[str, Any], canc_flt: list[dict[str, Any]]
) -> dict[str, SemanticMetricModel]:
    """Seed ratio, multi-stage plan, and multi-fact plan bundle metrics."""
    t, c = meta["tables"], meta["cols"]
    r_body = _ratio_body(c["ord_amount"], c["ord_id"], canc_flt)
    s_body = _single_stage_plan_body("sales_stage", "orders", c["cust_region"], "orders.amount")
    f_body = _single_stage_plan_body("refund_stage", "returns", c["cust_region"], "returns.refund_amount")
    ratio = await _add_metric(session, db_id, t["orders"], c["ord_id"].id, "Revenue Per Cancelled Order", "SUM", r_body)
    sales = await _add_metric(session, db_id, t["orders"], c["ord_id"].id, "Planned Sales", "COUNT", s_body)
    refunds = await _add_metric(session, db_id, t["returns"], c["ret_id"].id, "Planned Refunds", "COUNT", f_body)
    multi = await _seed_multi_stage_metric(session, db_id, meta)
    return {"zero_denom_ratio": ratio, "sales_plan": sales, "refunds_plan": refunds, "multi_stage": multi}


async def _seed_multi_stage_metric(session: AsyncSession, db_id: int, meta: dict[str, Any]) -> SemanticMetricModel:
    """Seed a multi-stage customer order density metric."""
    t, c = meta["tables"], meta["cols"]
    s1_grp = [
        {"name": "customer_id", "expression": "orders.customer_id", "column_id": c["ord_cust_id"].id},
        {"name": "region", "expression": "customers.region", "column_id": c["cust_region"].id},
    ]
    s1_agg = [{"name": "order_count", "function": "COUNT", "expression": "orders.id"}]
    s2_grp = [{"name": "region", "expression": "per_customer.region", "column_id": c["cust_region"].id}]
    s2_agg = [{"name": "active_customers", "function": "COUNT_DISTINCT", "expression": "per_customer.customer_id"}]
    stages = [
        {
            "name": "per_customer",
            "base_entity": "orders",
            "joins": ["customers"],
            "group_by": s1_grp,
            "aggregates": s1_agg,
        },
        {"name": "regional_summary", "source_stage": "per_customer", "group_by": s2_grp, "aggregates": s2_agg},
    ]
    body = {
        "base_entity": "orders",
        "formula": {"function": "COUNT", "expression": "*"},
        "query_plan": {"stages": stages, "output_expression": "regional_summary.active_customers"},
        "filters": [],
    }
    return await _add_metric(session, db_id, t["orders"], c["ord_id"].id, "Active Customer Share", "COUNT", body)


def _rows_as_dicts(exec_result: Any) -> list[dict[str, Any]]:
    """Convert execute_compiled_query tabular output into column-keyed row dicts."""
    return [dict(zip(exec_result.columns, row, strict=True)) for row in exec_result.rows]


async def _assert_compiles_all_dialects(
    session: AsyncSession, db: SemanticDatabaseModel, spec: SemanticQuerySpec
) -> None:
    """Assert that a query spec compiles into valid SQL for SQLite, PostgreSQL, and MySQL."""
    for db_type, dialect in (("sqlite", "sqlite"), ("postgresql", "postgres"), ("mysql", "mysql")):
        db.db_type = db_type
        await session.flush()
        compiled = await SemanticQueryCompiler(session).compile(db.id, spec)
        sqlglot.parse_one(compiled.sql, read=dialect)
    db.db_type = "sqlite"
    await session.flush()


@pytest.mark.asyncio
async def test_baseline_order_fixture_and_conditional_aggregates(async_session: AsyncSession, tmp_path: Path) -> None:
    """1 order (100), 2 line items, 3 payments returns 100 revenue and 0 cancelled orders."""
    conn_url = _create_commerce_sqlite_db(tmp_path / "commerce_order.db")
    catalog = await _seed_commerce_catalog(async_session)
    db = catalog["db"]
    m = catalog["metrics"]
    spec = SemanticQuerySpec(metric_ids=[m["revenue"].id, m["cancelled"].id])
    for db_type, dialect in (("sqlite", "sqlite"), ("postgresql", "postgres")):
        db.db_type = db_type
        await async_session.flush()
        compiled = await SemanticQueryCompiler(async_session).compile(db.id, spec)
        sqlglot.parse_one(compiled.sql, read=dialect)
    db.db_type = "sqlite"
    await async_session.flush()
    compiled = await SemanticQueryCompiler(async_session).compile(db.id, spec)
    result = await execute_compiled_query(conn_url, "sqlite", compiled)

    assert _rows_as_dicts(result) == [{f"metric_{m['revenue'].id}": 100, f"metric_{m['cancelled'].id}": 0}]


@pytest.mark.asyncio
async def test_baseline_empty_set_and_zero_denominator_ratio(async_session: AsyncSession, tmp_path: Path) -> None:
    """Empty filter set returns NULL for SUM and 0 for COUNT; 0 denominator ratio returns NULL."""
    conn_url = _create_commerce_sqlite_db(tmp_path / "commerce_empty_ratio.db")
    catalog = await _seed_commerce_catalog(async_session)
    db, c, m = catalog["db"], catalog["cols"], catalog["metrics"]
    empty_spec = SemanticQuerySpec(
        metric_ids=[m["revenue"].id, m["cancelled"].id],
        filters=[SemanticQueryFilter(column_id=c["ord_id"].id, operator="eq", value=999)],
    )
    ratio_spec = SemanticQuerySpec(metric_ids=[m["zero_denom_ratio"].id])

    for db_type, dialect in (("sqlite", "sqlite"), ("postgresql", "postgres")):
        db.db_type = db_type
        await async_session.flush()
        ratio_compiled = await SemanticQueryCompiler(async_session).compile(db.id, ratio_spec)
        sqlglot.parse_one(ratio_compiled.sql, read=dialect)
    db.db_type = "sqlite"
    await async_session.flush()
    empty_compiled = await SemanticQueryCompiler(async_session).compile(db.id, empty_spec)
    empty_res = await execute_compiled_query(conn_url, "sqlite", empty_compiled)
    ratio_compiled = await SemanticQueryCompiler(async_session).compile(db.id, ratio_spec)
    ratio_res = await execute_compiled_query(conn_url, "sqlite", ratio_compiled)

    assert _rows_as_dicts(empty_res) == [{f"metric_{m['revenue'].id}": None, f"metric_{m['cancelled'].id}": 0}]
    assert _rows_as_dicts(ratio_res) == [{f"metric_{m['zero_denom_ratio'].id}": None}]


@pytest.mark.asyncio
async def test_gap_mysql_simple_conditional_aggregate_guardrail_dialect(
    async_session: AsyncSession,
) -> None:
    """MySQL simple conditional aggregate and filtered ratio should validate under MySQL dialect."""
    catalog = await _seed_commerce_catalog(async_session)
    db, m = catalog["db"], catalog["metrics"]
    db.db_type = "mysql"
    await async_session.flush()
    spec = SemanticQuerySpec(metric_ids=[m["revenue"].id, m["cancelled"].id])
    compiled = await SemanticQueryCompiler(async_session).compile(db.id, spec)
    sqlglot.parse_one(compiled.sql, read="mysql")


@pytest.mark.asyncio
async def test_baseline_multi_stage_and_plan_bundle_null_and_missing_fact_groups(
    async_session: AsyncSession, tmp_path: Path
) -> None:
    """Multi-stage plan and multi-fact plan bundle preserve NULL keys and single-fact groups."""
    extra_orders = (
        'INSERT INTO "orders" VALUES '
        "(2, 2, 200, 'completed', 'ORD-2', '2026-01-02'), (3, 3, 50, 'completed', 'ORD-3', '2026-01-03')",
    )
    conn_url = _create_commerce_sqlite_db(tmp_path / "commerce_plans.db", extra_orders)
    catalog = await _seed_commerce_catalog(async_session)
    db, c, m = catalog["db"], catalog["cols"], catalog["metrics"]
    dims = [DimensionSelection(column_id=c["cust_region"].id)]
    stage_spec = SemanticQuerySpec(metric_ids=[m["multi_stage"].id], dimensions=dims)
    bundle_spec = SemanticQuerySpec(metric_ids=[m["sales_plan"].id, m["refunds_plan"].id], dimensions=dims)
    await _assert_compiles_all_dialects(async_session, db, stage_spec)
    await _assert_compiles_all_dialects(async_session, db, bundle_spec)
    bundle_compiled = await SemanticQueryCompiler(async_session).compile(db.id, bundle_spec)
    bundle_res = await execute_compiled_query(conn_url, "sqlite", bundle_compiled)
    by_region = {row[f"dimension_{c['cust_region'].id}"]: row for row in _rows_as_dicts(bundle_res)}
    sales_key, refund_key = f"metric_{m['sales_plan'].id}", f"metric_{m['refunds_plan'].id}"
    assert (by_region["north"][sales_key], by_region["north"][refund_key]) == (100, 25)
    assert (by_region["south"][sales_key], by_region["south"][refund_key]) == (200, None)
    assert (by_region[None][sales_key], by_region[None][refund_key]) == (50, 10)


@pytest.mark.asyncio
async def test_gap_task2_parameter_binding_follows_column_type(async_session: AsyncSession) -> None:
    """TEXT columns must keep ISO-date strings as str; invalid INTEGER literals must fail closed."""
    catalog = await _seed_commerce_catalog(async_session)
    db, c, m = catalog["db"], catalog["cols"], catalog["metrics"]
    text_spec = SemanticQuerySpec(
        metric_ids=[m["revenue"].id],
        filters=[SemanticQueryFilter(column_id=c["ord_code"].id, operator="eq", value="2026-01-01")],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db.id, text_spec)
    assert all(type(val) is str for val in compiled.parameters.values())

    bad_int_spec = SemanticQuerySpec(
        metric_ids=[m["revenue"].id],
        filters=[SemanticQueryFilter(column_id=c["ord_id"].id, operator="eq", value="not-an-int")],
    )
    with pytest.raises(SemanticCompileError) as exc_info:
        await SemanticQueryCompiler(async_session).compile(db.id, bad_int_spec)
    assert exc_info.value.code == "INVALID_FILTER_VALUE"


@pytest.mark.asyncio
async def test_gap_task3_unified_iso_week_and_month_time_buckets(async_session: AsyncSession, tmp_path: Path) -> None:
    """Simple and plan queries must emit identical YYYY-MM and ISO YYYY-Www buckets."""
    conn_url = _create_commerce_sqlite_db(tmp_path / "commerce_time.db")
    catalog = await _seed_commerce_catalog(async_session)
    db, c, m = catalog["db"], catalog["cols"], catalog["metrics"]
    week_spec = SemanticQuerySpec(
        metric_ids=[m["revenue"].id],
        dimensions=[DimensionSelection(column_id=c["ord_created"].id, time_grain="week")],
    )
    month_spec = SemanticQuerySpec(
        metric_ids=[m["revenue"].id],
        dimensions=[DimensionSelection(column_id=c["ord_created"].id, time_grain="month")],
    )
    week_compiled = await SemanticQueryCompiler(async_session).compile(db.id, week_spec)
    month_compiled = await SemanticQueryCompiler(async_session).compile(db.id, month_spec)
    week_rows = _rows_as_dicts(await execute_compiled_query(conn_url, "sqlite", week_compiled))
    month_rows = _rows_as_dicts(await execute_compiled_query(conn_url, "sqlite", month_compiled))

    assert week_rows[0][f"dimension_{c['ord_created'].id}"] == "2026-W01"
    assert month_rows[0][f"dimension_{c['ord_created'].id}"] == "2026-01"


@pytest.mark.asyncio
async def test_gap_task4_one_to_many_child_filters_use_exists_without_fanout(
    async_session: AsyncSession, tmp_path: Path
) -> None:
    """1 order (100) with 2 items and 3 payments filtered by child tables must return 100 via EXISTS."""
    conn_url = _create_commerce_sqlite_db(tmp_path / "commerce_fanout.db")
    catalog = await _seed_commerce_catalog(async_session)
    db, c, m = catalog["db"], catalog["cols"], catalog["metrics"]
    spec = SemanticQuerySpec(
        metric_ids=[m["revenue"].id],
        filters=[
            SemanticQueryFilter(column_id=c["item_product"].id, operator="eq", value="Widget"),
            SemanticQueryFilter(column_id=c["pay_method"].id, operator="eq", value="card"),
        ],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db.id, spec)
    result = await execute_compiled_query(conn_url, "sqlite", compiled)

    assert "EXISTS" in compiled.sql.upper()
    assert _rows_as_dicts(result) == [{f"metric_{m['revenue'].id}": 100}]


@pytest.mark.asyncio
async def test_gap_task5_multi_fact_simple_and_mixed_plan_metrics_lower_to_bundle(
    async_session: AsyncSession, tmp_path: Path
) -> None:
    """Simple metrics across orders+returns and mixed simple+plan metrics lower to a shared-grain bundle."""
    conn_url = _create_commerce_sqlite_db(tmp_path / "commerce_multifact.db")
    catalog = await _seed_commerce_catalog(async_session)
    db, c, m = catalog["db"], catalog["cols"], catalog["metrics"]
    dims = [DimensionSelection(column_id=c["cust_region"].id)]
    multi_fact_spec = SemanticQuerySpec(metric_ids=[m["revenue"].id, m["refunds_simple"].id], dimensions=dims)
    mixed_spec = SemanticQuerySpec(metric_ids=[m["revenue"].id, m["refunds_plan"].id], dimensions=dims)
    compiled_multi = await SemanticQueryCompiler(async_session).compile(db.id, multi_fact_spec)
    compiled_mixed = await SemanticQueryCompiler(async_session).compile(db.id, mixed_spec)
    res_multi = _rows_as_dicts(await execute_compiled_query(conn_url, "sqlite", compiled_multi))
    res_mixed = _rows_as_dicts(await execute_compiled_query(conn_url, "sqlite", compiled_mixed))
    dim_key = f"dimension_{c['cust_region'].id}"
    by_reg = {row[dim_key]: row for row in res_multi}
    assert by_reg["north"][f"metric_{m['revenue'].id}"] == 100
    assert by_reg["north"][f"metric_{m['refunds_simple'].id}"] == 25
    assert by_reg[None][f"metric_{m['refunds_simple'].id}"] == 10
    mixed_by_reg = {row[dim_key]: row for row in res_mixed}
    assert set(mixed_by_reg) == {"north", None}
    assert mixed_by_reg["north"][f"metric_{m['revenue'].id}"] == 100
    assert mixed_by_reg["north"][f"metric_{m['refunds_plan'].id}"] == 25
    assert mixed_by_reg[None][f"metric_{m['revenue'].id}"] is None
    assert mixed_by_reg[None][f"metric_{m['refunds_plan'].id}"] == 10
