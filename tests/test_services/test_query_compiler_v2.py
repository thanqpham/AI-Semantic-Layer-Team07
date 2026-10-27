"""Behavior tests for the canonical semantic query compiler interface."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    CanonicalRelationshipModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQueryRequest, SemanticQuerySpec
from src.services.query_compiler import SemanticQueryCompiler
from src.services.semantic_compile_error import SemanticCompileError


def test_query_request_passes_optional_order_to_compiler_spec() -> None:
    request = SemanticQueryRequest(metric_ids=[5], dimensions=[DimensionSelection(column_id=3)], order_by="metric_desc")
    assert request.to_spec().order_by == "metric_desc"
    assert SemanticQueryRequest(metric_ids=[5]).to_spec().order_by is None


async def _seed_filtered_metrics(db: AsyncSession) -> tuple[int, list[int]]:
    semantic_db = SemanticDatabaseModel(
        created_by=1, display_name="Sales", db_type="sqlite", conn_url_enc="encrypted", status="draft"
    )
    db.add(semantic_db)
    await db.flush()
    table = SemanticTableModel(
        db_id=semantic_db.id,
        table_name="orders",
        business_name="Đơn hàng",
        description="",
        primary_key_column="id",
    )
    db.add(table)
    await db.flush()
    columns = [
        SemanticColumnModel(
            table_id=table.id,
            column_name=name,
            data_type=data_type,
            business_name=name,
            is_primary_key=name == "id",
        )
        for name, data_type in [
            ("id", "INTEGER"),
            ("amount", "NUMERIC"),
            ("status", "TEXT"),
            ("is_test", "BOOLEAN"),
        ]
    ]
    db.add_all(columns)
    await db.flush()
    metrics = [
        _metric(semantic_db.id, table.id, columns[1].id, columns[2].id, columns[0].id, status)
        for status in ("completed", "cancelled")
    ]
    db.add_all(metrics)
    await db.commit()
    return semantic_db.id, [metric.id for metric in metrics]


async def _seed_shared_filter_metrics(db: AsyncSession) -> tuple[int, list[int]]:
    semantic_db = SemanticDatabaseModel(
        created_by=1, display_name="Sales", db_type="sqlite", conn_url_enc="encrypted", status="draft"
    )
    db.add(semantic_db)
    await db.flush()
    table = SemanticTableModel(
        db_id=semantic_db.id,
        table_name="orders",
        business_name="Đơn hàng",
        description="",
        primary_key_column="id",
    )
    db.add(table)
    await db.flush()
    columns = [
        SemanticColumnModel(
            table_id=table.id,
            column_name=name,
            data_type=data_type,
            business_name=name,
            is_primary_key=name == "id",
        )
        for name, data_type in [
            ("id", "INTEGER"),
            ("amount", "NUMERIC"),
            ("status", "TEXT"),
            ("is_test", "INTEGER"),
        ]
    ]
    db.add_all(columns)
    await db.flush()
    metrics = [
        _shared_metric(semantic_db.id, table.id, columns[1].id, columns[0].id, name, filters)
        for name, filters in (
            (
                "Revenue completed",
                [{"field": "status", "column_id": columns[2].id, "operator": "eq", "value": "completed"}],
            ),
            (
                "Revenue completed test",
                [
                    {"field": "status", "column_id": columns[2].id, "operator": "eq", "value": "completed"},
                    {"field": "is_test", "column_id": columns[3].id, "operator": "eq", "value": 0},
                ],
            ),
        )
    ]
    db.add_all(metrics)
    await db.commit()
    return semantic_db.id, [metric.id for metric in metrics]


def _metric(
    db_id: int,
    table_id: int,
    amount_id: int,
    status_id: int,
    grain_id: int,
    status: str,
) -> SemanticMetricModel:
    definition = {
        "schema_version": 2,
        "metric": {
            "name": f"Revenue {status}",
            "formula": {
                "function": "SUM",
                "expression": "amount",
                "expression_ast": {"kind": "column", "column_id": amount_id},
            },
            "base_entity": "orders",
            "base_entity_id": table_id,
            "grain": {"column_ids": [grain_id]},
            "filters": [{"field": "status", "column_id": status_id, "operator": "eq", "value": status}],
            "status": "approved",
            "confidence": "high",
            "excluded_notes": "",
        },
    }
    return SemanticMetricModel(
        db_id=db_id,
        created_by=1,
        name=f"Revenue {status}",
        description="",
        sql_template="",
        source="ai",
        status="approved",
        base_entity_id=table_id,
        formula="",
        aggregation_type="SUM",
        definition=definition,
    )


def _grouped_sales_plan(category_id: int) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "metric": {
            "name": "Sales by category",
            "base_entity": "orders",
            "formula": {"function": "SUM", "expression": "orders.amount"},
            "query_plan": {
                "stages": [
                    {
                        "name": "sales",
                        "base_entity": "orders",
                        "group_by": [{"name": "category", "expression": "orders.category", "column_id": category_id}],
                        "aggregates": [{"name": "total_amount", "function": "SUM", "expression": "orders.amount"}],
                    }
                ],
                "output_expression": "sales.total_amount",
            },
            "filters": [],
            "status": "approved",
        },
    }


def _shared_metric(
    db_id: int,
    table_id: int,
    amount_id: int,
    grain_id: int,
    name: str,
    filters: list[dict[str, Any]],
) -> SemanticMetricModel:
    definition = {
        "schema_version": 2,
        "metric": {
            "name": name,
            "formula": {
                "function": "SUM",
                "expression": "amount",
                "expression_ast": {"kind": "column", "column_id": amount_id},
            },
            "base_entity": "orders",
            "base_entity_id": table_id,
            "grain": {"column_ids": [grain_id]},
            "filters": filters,
            "status": "approved",
            "confidence": "high",
            "excluded_notes": "",
        },
    }
    return SemanticMetricModel(
        db_id=db_id,
        created_by=1,
        name=name,
        description="",
        sql_template="",
        source="ai",
        status="approved",
        base_entity_id=table_id,
        formula="",
        aggregation_type="SUM",
        definition=definition,
    )


@pytest.mark.asyncio
async def test_divergent_filters_keep_residual_case_and_empty_where(async_session: AsyncSession) -> None:
    """No shared predicate -> no WHERE; each metric keeps its own CASE."""
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=metric_ids))
    assert compiled.sql.count("CASE WHEN") == 2
    assert " WHERE " not in compiled.sql
    assert compiled.parameters == {"metric_0": "completed", "metric_1": "cancelled"}


@pytest.mark.asyncio
async def test_shared_filters_hoist_to_where_and_residual_stays_in_case(async_session: AsyncSession) -> None:
    """Shared predicate -> WHERE once (bound first); extra predicate stays as CASE."""
    db_id, metric_ids = await _seed_shared_filter_metrics(async_session)
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=metric_ids))
    assert 'WHERE "orders"."status" = :fixed_0' in compiled.sql
    assert compiled.sql.count("CASE WHEN") == 1
    assert 'THEN "orders"."amount" END) AS "metric_' in compiled.sql
    # fixed bound trước (len=0 -> fixed_0); residual của metric 2 bound kế (len=1 -> metric_1)
    assert compiled.parameters == {"fixed_0": "completed", "metric_1": 0}


@pytest.mark.asyncio
async def test_single_metric_filter_all_hoisted_no_case(async_session: AsyncSession) -> None:
    """Single metric -> every filter hoisted to WHERE, no CASE wrapper."""
    db_id, metric_ids = await _seed_shared_filter_metrics(async_session)
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric_ids[1]]))
    assert "CASE WHEN" not in compiled.sql
    assert "WHERE" in compiled.sql
    assert ":fixed_0" in compiled.sql and ":fixed_1" in compiled.sql


@pytest.mark.asyncio
async def test_runtime_filter_adds_its_required_join(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    orders = await _table(async_session, db_id, "orders")
    customers = SemanticTableModel(
        db_id=db_id, table_name="customers", business_name="Khách hàng", description="", primary_key_column="id"
    )
    async_session.add(customers)
    await async_session.flush()
    customer_id = SemanticColumnModel(
        table_id=orders.id, column_name="customer_id", data_type="INTEGER", business_name="Mã khách hàng"
    )
    customer_pk = SemanticColumnModel(
        table_id=customers.id,
        column_name="id",
        data_type="INTEGER",
        business_name="Mã khách hàng",
        is_primary_key=True,
    )
    segment = SemanticColumnModel(
        table_id=customers.id, column_name="segment", data_type="TEXT", business_name="Phân khúc"
    )
    async_session.add_all([customer_id, customer_pk, segment])
    await async_session.flush()
    async_session.add(
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=orders.id,
            to_entity_id=customers.id,
            relationship_type="many_to_one",
            join_condition="orders.customer_id = customers.id",
            column_pairs=[{"from_column_id": customer_id.id, "to_column_id": customer_pk.id}],
        )
    )
    await async_session.commit()

    query = SemanticQuerySpec(
        metric_ids=[metric_ids[0]],
        filters=[SemanticQueryFilter(column_id=segment.id, operator="eq", value="enterprise")],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, query)

    assert 'JOIN "customers"' in compiled.sql
    assert '"customers"."segment" = :runtime_1' in compiled.sql


@pytest.mark.asyncio
async def test_time_dimension_compiles_with_requested_sqlite_grain(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    orders = await _table(async_session, db_id, "orders")
    created_at = SemanticColumnModel(
        table_id=orders.id,
        column_name="created_at",
        data_type="TIMESTAMP",
        business_name="Ngày tạo",
        is_time_dimension=True,
    )
    async_session.add(created_at)
    await async_session.commit()

    query = SemanticQuerySpec(
        metric_ids=[metric_ids[0]],
        dimensions=[DimensionSelection(column_id=created_at.id, time_grain="month")],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, query)

    assert """strftime('%Y-%m', "orders"."created_at")""" in compiled.sql
    assert f'"dimension_{created_at.id}"' in compiled.sql


@pytest.mark.asyncio
async def test_optional_dashboard_order_does_not_change_default_queries(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    orders = await _table(async_session, db_id, "orders")
    column = SemanticColumnModel(table_id=orders.id, column_name="category", data_type="TEXT", business_name="Category")
    async_session.add(column)
    await async_session.commit()
    compiler = SemanticQueryCompiler(async_session)
    base = dict(metric_ids=[metric_ids[0]], dimensions=[DimensionSelection(column_id=column.id)], limit=101)

    default = await compiler.compile(db_id, SemanticQuerySpec(**base))
    ranked = await compiler.compile(db_id, SemanticQuerySpec(**base, order_by="metric_desc"))
    recent = await compiler.compile(db_id, SemanticQuerySpec(**base, order_by="dimension_desc"))

    assert "ORDER BY" not in default.sql
    assert " IS NULL, 2 DESC, 1 ASC\nLIMIT 101" in ranked.sql
    assert " IS NULL, 1 DESC\nLIMIT 101" in recent.sql
    await async_session.execute(text('CREATE TABLE "orders" ("id" INTEGER, "amount" NUMERIC, "status" TEXT, "category" TEXT)'))
    await async_session.execute(text("INSERT INTO orders VALUES (1, 5, 'completed', 'A'), (2, 10, 'completed', 'B'), (3, 3, 'completed', 'C')"))
    ranked_rows = (await async_session.execute(text(ranked.sql), ranked.parameters)).all()
    recent_rows = (await async_session.execute(text(recent.sql), recent.parameters)).all()
    assert [row[0] for row in ranked_rows] == ["B", "A", "C"]
    assert [row[0] for row in recent_rows] == ["C", "B", "A"]


@pytest.mark.asyncio
async def test_multi_table_plan_orders_before_applying_limit(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    orders = await _table(async_session, db_id, "orders")
    category = SemanticColumnModel(
        table_id=orders.id, column_name="category", data_type="TEXT", business_name="Category"
    )
    async_session.add(category)
    await async_session.flush()
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    assert metric is not None
    metric.definition = _grouped_sales_plan(category.id)
    await async_session.commit()
    await async_session.execute(
        text('CREATE TABLE "orders" ("id" INTEGER, "amount" NUMERIC, "status" TEXT, "category" TEXT)')
    )
    await async_session.execute(
        text(
            "INSERT INTO orders VALUES "
            "(1, 5, 'completed', 'A'), (2, 20, 'completed', 'B'), "
            "(3, 10, 'completed', 'C'), (4, 30, 'completed', 'D')"
        )
    )
    compiler = SemanticQueryCompiler(async_session)
    for order_by, expected in (("metric_desc", ["D", "B"]), ("dimension_desc", ["D", "C"])):
        query = SemanticQuerySpec(
            metric_ids=[metric.id],
            dimensions=[DimensionSelection(column_id=category.id)],
            limit=2,
            order_by=order_by,
        )
        compiled = await compiler.compile(db_id, query)
        assert compiled.sql.index("ORDER BY") < compiled.sql.index("LIMIT")
        rows = await async_session.execute(text(compiled.sql), compiled.parameters)
        assert [row[0] for row in rows.all()] == expected


@pytest.mark.asyncio
async def test_reverse_many_to_one_is_rejected_as_fanout(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    orders = await _table(async_session, db_id, "orders")
    customers = SemanticTableModel(
        db_id=db_id, table_name="customers", business_name="Khách hàng", description="", primary_key_column="id"
    )
    async_session.add(customers)
    await async_session.flush()
    customer_id = SemanticColumnModel(
        table_id=customers.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
    )
    async_session.add(customer_id)
    await async_session.flush()
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    metric.base_entity_id = customers.id
    metric.definition["metric"]["base_entity"] = "customers"
    metric.definition["metric"]["formula"] = {
        "function": "COUNT",
        "expression": "*",
        "expression_ast": {"kind": "literal", "value": 1},
    }
    metric.definition["metric"]["base_entity_id"] = customers.id
    metric.definition["metric"]["grain"] = {"column_ids": [customer_id.id]}
    metric.definition["metric"]["filters"] = []
    amount = await _column(async_session, orders.id, "amount")
    async_session.add(
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=orders.id,
            to_entity_id=customers.id,
            relationship_type="many_to_one",
            join_condition="orders.customer_id = customers.id",
            relationship_key="orders_customer",
            validation_status="valid",
        )
    )
    await async_session.commit()

    query = SemanticQuerySpec(
        metric_ids=[metric.id],
        dimensions=[DimensionSelection(column_id=amount.id)],
    )
    with pytest.raises(SemanticCompileError) as error:
        await SemanticQueryCompiler(async_session).compile(db_id, query)
    assert error.value.code == "UNSAFE_FANOUT"


@pytest.mark.asyncio
async def test_compiler_normalizes_date_parameters(async_session: AsyncSession) -> None:
    """Date strings in metric filters are normalized to date objects in parameters."""
    from datetime import date

    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    table = await _table(async_session, db_id, "orders")
    created_col = SemanticColumnModel(
        table_id=table.id,
        column_name="created_at",
        data_type="TIMESTAMP",
        business_name="Created At",
        is_time_dimension=True,
    )
    async_session.add(created_col)
    await async_session.flush()

    metric.definition["metric"]["filters"] = [
        {"field": "created_at", "operator": "gte", "value": "2025-01-01", "column_id": created_col.id},
        {"field": "created_at", "operator": "lt", "value": "2025-02-01", "column_id": created_col.id},
    ]
    await async_session.commit()

    query = SemanticQuerySpec(metric_ids=[metric.id])
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, query)
    assert compiled.parameters["fixed_0"] == date(2025, 1, 1)
    assert compiled.parameters["fixed_1"] == date(2025, 2, 1)


@pytest.mark.asyncio
async def test_integer_column_coerces_string_literal(async_session: AsyncSession) -> None:
    """Filter value "0" on an INTEGER column binds as int 0; TEXT filter untouched."""
    db_id, metric_ids = await _seed_shared_filter_metrics(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_ids[1])
    definition = dict(metric.definition)
    filters = definition["metric"]["filters"]
    filters[1] = {**filters[1], "value": "0"}
    metric.definition = definition
    await async_session.commit()
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric_ids[1]]))
    assert compiled.parameters == {"fixed_0": "completed", "fixed_1": 0}


@pytest.mark.asyncio
async def test_text_column_keeps_string_literal(async_session: AsyncSession) -> None:
    """TEXT column values are never coerced."""
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=metric_ids))
    assert compiled.parameters == {"metric_0": "completed", "metric_1": "cancelled"}


@pytest.mark.asyncio
async def test_non_numeric_string_stays_uncoerced(async_session: AsyncSession) -> None:
    """ "abc" on an INTEGER column fails open: value unchanged."""
    db_id, metric_ids = await _seed_shared_filter_metrics(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_ids[1])
    definition = dict(metric.definition)
    filters = definition["metric"]["filters"]
    filters[1] = {**filters[1], "value": "abc"}
    metric.definition = definition
    await async_session.commit()
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric_ids[1]]))
    assert compiled.parameters["fixed_1"] == "abc"


@pytest.mark.asyncio
async def test_numeric_column_coerces_float_string(async_session: AsyncSession) -> None:
    """FLOAT column + "1.5" -> 1.5 (float)."""
    db_id, metric_ids = await _seed_shared_filter_metrics(async_session)
    table = await _table(async_session, db_id, "orders")
    ratio = SemanticColumnModel(table_id=table.id, column_name="ratio", data_type="FLOAT", business_name="Tỷ lệ")
    async_session.add(ratio)
    await async_session.flush()
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    definition = dict(metric.definition)
    definition["metric"]["filters"] = [{"field": "ratio", "column_id": ratio.id, "operator": "gt", "value": "1.5"}]
    metric.definition = definition
    await async_session.commit()
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric_ids[0]]))
    assert compiled.parameters == {"fixed_0": 1.5}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scale", "scope_status", "expected"),
    [(1, "completed", 50.0), (100, "completed", 5000.0), (1, "missing", None)],
)
async def test_compile_ratio_metric_uses_independent_aggregates_and_filters(
    async_session: AsyncSession,
    scale: int,
    scope_status: str,
    expected: float | None,
) -> None:
    """Ratio sides aggregate independently and apply shared and side-specific filters."""
    db_id, _ = await _seed_filtered_metrics(async_session)
    table = await _table(async_session, db_id, "orders")
    id_col = await _column(async_session, table.id, "id")
    amount_col = await _column(async_session, table.id, "amount")
    status_col = await _column(async_session, table.id, "status")
    test_col = await _column(async_session, table.id, "is_test")

    ratio_def = {
        "schema_version": 2,
        "metric": {
            "name": "Average completed amount",
            "formula": {
                "function": "SUM",
                "expression": "amount",
                "expression_ast": {"kind": "column", "column_id": amount_col.id},
                "ratio": {
                    "numerator": {
                        "function": "SUM",
                        "expression": "amount",
                        "expression_ast": {"kind": "column", "column_id": amount_col.id},
                        "filters": [
                            {"field": "is_test", "column_id": test_col.id, "operator": "eq", "value": 0}
                        ],
                    },
                    "denominator": {
                        "function": "COUNT_DISTINCT",
                        "expression": "id",
                        "expression_ast": {"kind": "column", "column_id": id_col.id},
                    },
                    "scale": scale,
                },
            },
            "base_entity": "orders",
            "base_entity_id": table.id,
            "grain": {"column_ids": [id_col.id]},
            "filters": [{"field": "status", "column_id": status_col.id, "operator": "eq", "value": scope_status}],
            "status": "approved",
            "confidence": "high",
            "excluded_notes": "",
        },
    }
    ratio_metric = SemanticMetricModel(
        db_id=db_id,
        created_by=1,
        name="Average completed amount",
        description="",
        sql_template="",
        source="ai",
        status="approved",
        base_entity_id=table.id,
        formula="",
        aggregation_type="SUM",
        definition=ratio_def,
    )
    async_session.add(ratio_metric)
    await async_session.commit()
    await async_session.execute(text(
        'CREATE TABLE "orders" ("id" INTEGER, "amount" NUMERIC, "status" TEXT, "is_test" INTEGER)'
    ))
    await async_session.execute(
        text('INSERT INTO "orders" VALUES (1, 100, \'completed\', 0), (2, 300, \'completed\', 1), (3, 200, \'cancelled\', 0)')
    )

    query = SemanticQuerySpec(metric_ids=[ratio_metric.id])
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, query)
    assert "NULLIF" in compiled.sql
    assert "SUM(CASE WHEN" in compiled.sql
    assert "COUNT(DISTINCT" in compiled.sql
    result = await async_session.execute(text(compiled.sql), compiled.parameters)
    value = result.scalar_one()
    if expected is None:
        assert value is None
    else:
        assert value == pytest.approx(expected)


@pytest.mark.asyncio
async def test_legacy_division_metric_requires_review(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    assert metric is not None
    definition = dict(metric.definition)
    amount_id = (await _column(async_session, metric.base_entity_id, "amount")).id
    id_id = (await _column(async_session, metric.base_entity_id, "id")).id
    definition["metric"]["formula"]["expression"] = "amount / id"
    definition["metric"]["formula"]["expression_ast"] = {
        "kind": "div",
        "children": [
            {"kind": "column", "column_id": amount_id},
            {"kind": "column", "column_id": id_id},
        ],
    }
    metric.definition = definition
    await async_session.commit()

    with pytest.raises(SemanticCompileError) as error:
        await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric.id]))
    assert error.value.code == "METRIC_NEEDS_REVIEW"


@pytest.mark.asyncio
async def test_multi_table_plan_compiles_nested_customer_ratio(async_session: AsyncSession) -> None:
    """Aggregate orders per customer, then count repeat customers over all customers."""
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    orders = await _table(async_session, db_id, "orders")
    customers = SemanticTableModel(
        db_id=db_id, table_name="customers", business_name="Customers", description="", primary_key_column="id"
    )
    async_session.add(customers)
    await async_session.flush()
    customer_id = SemanticColumnModel(
        table_id=customers.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
    )
    region = SemanticColumnModel(
        table_id=customers.id, column_name="region", data_type="TEXT", business_name="Region"
    )
    order_customer = SemanticColumnModel(
        table_id=orders.id, column_name="customer_id", data_type="INTEGER", business_name="Customer ID"
    )
    async_session.add_all([region, order_customer])
    await async_session.flush()
    async_session.add(customer_id)
    await async_session.flush()
    async_session.add(
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=orders.id,
            to_entity_id=customers.id,
            relationship_type="many_to_one",
            join_condition="orders.customer_id = customers.id",
            relationship_key="orders_customer_plan_test",
            column_pairs=[{"from_column_id": order_customer.id, "to_column_id": customer_id.id}],
            validation_status="valid",
        )
    )
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    assert metric is not None
    metric.name = "Returning customer rate plan"
    metric.definition = {
        "schema_version": 3,
        "metric": {
            "name": metric.name,
            "base_entity": "orders",
            "formula": {"function": "COUNT", "expression": "*"},
            "query_plan": {
                "stages": [
                    {
                        "name": "customer_orders",
                        "base_entity": "orders",
                        "joins": ["customers"],
                        "group_by": [
                            {"name": "customer_id", "expression": "customers.id", "column_id": customer_id.id}
                        ],
                        "aggregates": [
                            {"name": "order_count", "function": "COUNT_DISTINCT", "expression": "orders.id"}
                        ],
                    },
                    {
                        "name": "repeat_customers",
                        "source_stage": "customer_orders",
                        "aggregates": [
                            {"name": "customers", "function": "COUNT", "expression": "*", "filters": [
                                {"field": "order_count", "operator": "gte", "value": 2}
                            ]}
                        ],
                    },
                    {
                        "name": "all_customers",
                        "source_stage": "customer_orders",
                        "aggregates": [{"name": "customers", "function": "COUNT", "expression": "*"}],
                    },
                ],
                "output_expression": "repeat_customers.customers / all_customers.customers",
            },
            "filters": [],
            "status": "approved",
        },
    }
    await async_session.commit()
    await async_session.execute(text('CREATE TABLE "orders" ("id" INTEGER, "customer_id" INTEGER)'))
    await async_session.execute(text('CREATE TABLE "customers" ("id" INTEGER, "region" TEXT)'))
    await async_session.execute(text('INSERT INTO "customers" VALUES (1, \'north\'), (2, \'south\')'))
    await async_session.execute(text('INSERT INTO "orders" VALUES (1, 1), (2, 1), (3, 2)'))

    compiled = await SemanticQueryCompiler(async_session).compile(db_id, metric_ids=[metric.id], dimension_ids=[])
    assert "COUNT(DISTINCT" in compiled.sql
    assert "NULLIF" in compiled.sql
    result = await async_session.execute(text(compiled.sql), compiled.parameters)
    assert result.scalar_one() == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_qualified_source_stage_refs_compile_and_execute_by_region(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    orders = await _table(async_session, db_id, "orders")
    customers = SemanticTableModel(
        db_id=db_id, table_name="customers", business_name="Customers", description="", primary_key_column="id"
    )
    async_session.add(customers)
    await async_session.flush()
    order_customer = SemanticColumnModel(
        table_id=orders.id, column_name="customer_id", data_type="INTEGER", business_name="Customer ID"
    )
    customer_id = SemanticColumnModel(
        table_id=customers.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
    )
    region = SemanticColumnModel(table_id=customers.id, column_name="region", data_type="TEXT", business_name="Region")
    async_session.add_all([order_customer, customer_id, region])
    await async_session.flush()
    async_session.add(
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=orders.id,
            to_entity_id=customers.id,
            relationship_type="many_to_one",
            join_condition="orders.customer_id = customers.id",
            relationship_key="orders_customers_qualified_stage_test",
            column_pairs=[{"from_column_id": order_customer.id, "to_column_id": customer_id.id}],
            validation_status="valid",
        )
    )
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    assert metric is not None
    metric.name = "Returning customer rate by region"
    metric.definition = {
        "schema_version": 3,
        "metric": {
            "name": metric.name,
            "base_entity": "orders",
            "formula": {"function": "SUM", "expression": "amount"},
            "query_plan": {
                "stages": [
                    {
                        "name": "per_customer",
                        "base_entity": "orders",
                        "joins": ["customers"],
                        "group_by": [
                            {"name": "customer_id", "expression": "orders.customer_id", "column_id": order_customer.id},
                            {"name": "region", "expression": "customers.region", "column_id": region.id},
                        ],
                        "aggregates": [{"name": "order_count", "function": "COUNT_DISTINCT", "expression": "orders.id"}],
                        "filters": [{"field": "orders.status", "operator": "eq", "value": "completed"}],
                    },
                    {
                        "name": "repeat_customers",
                        "source_stage": "per_customer",
                        "group_by": [{"name": "region", "expression": "per_customer.region", "column_id": region.id}],
                        "aggregates": [{
                            "name": "customers",
                            "function": "COUNT_DISTINCT",
                            "expression": "per_customer.customer_id",
                            "filters": [{"field": "per_customer.order_count", "operator": "gte", "value": 2}],
                        }],
                    },
                    {
                        "name": "total_customers",
                        "source_stage": "per_customer",
                        "group_by": [{"name": "region", "expression": "per_customer.region", "column_id": region.id}],
                        "aggregates": [{"name": "customers", "function": "COUNT_DISTINCT", "expression": "per_customer.customer_id"}],
                    },
                ],
                "output_expression": "repeat_customers.customers / total_customers.customers",
            },
            "filters": [],
            "status": "approved",
        },
    }
    await async_session.commit()
    await async_session.execute(text('CREATE TABLE "orders" ("id" INTEGER, "customer_id" INTEGER, "amount" NUMERIC, "status" TEXT, "is_test" INTEGER)'))
    await async_session.execute(text('CREATE TABLE "customers" ("id" INTEGER, "region" TEXT)'))
    await async_session.execute(text('INSERT INTO "customers" VALUES (1, \'north\'), (2, \'south\')'))
    await async_session.execute(text('INSERT INTO "orders" VALUES (1, 1, 10, \'completed\', 0), (2, 1, 20, \'completed\', 0), (3, 2, 30, \'completed\', 0)'))

    compiled = await SemanticQueryCompiler(async_session).compile(
        db_id, SemanticQuerySpec(metric_ids=[metric.id], dimensions=[DimensionSelection(column_id=region.id)])
    )
    result = await async_session.execute(text(compiled.sql), compiled.parameters)
    assert result.all() == [("north", 1.0), ("south", 0.0)]


@pytest.mark.asyncio
async def test_multi_fact_plan_aligns_shared_dimension_and_compiles_all_dialects(
    async_session: AsyncSession,
) -> None:
    """Independent fact aggregates join only after both reach the same dimension grain."""
    import sqlglot

    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    orders = await _table(async_session, db_id, "orders")
    customers = SemanticTableModel(
        db_id=db_id, table_name="customers", business_name="Customers", description="", primary_key_column="id"
    )
    returns = SemanticTableModel(
        db_id=db_id, table_name="returns", business_name="Returns", description="", primary_key_column="id"
    )
    async_session.add_all([customers, returns])
    await async_session.flush()
    customer_id = SemanticColumnModel(
        table_id=customers.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
    )
    region = SemanticColumnModel(
        table_id=customers.id, column_name="region", data_type="TEXT", business_name="Region", is_time_dimension=False
    )
    order_customer = SemanticColumnModel(table_id=orders.id, column_name="customer_id", data_type="INTEGER", business_name="Customer ID")
    return_customer = SemanticColumnModel(table_id=returns.id, column_name="customer_id", data_type="INTEGER", business_name="Customer ID")
    return_id = SemanticColumnModel(
        table_id=returns.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
    )
    return_amount = SemanticColumnModel(table_id=returns.id, column_name="amount", data_type="NUMERIC", business_name="Amount")
    async_session.add_all([customer_id, region, order_customer, return_customer, return_id, return_amount])
    await async_session.flush()
    for source, foreign_key, key in ((orders, order_customer, "orders_region_plan"), (returns, return_customer, "returns_region_plan")):
        async_session.add(
            CanonicalRelationshipModel(
                connection_id=db_id,
                from_entity_id=source.id,
                to_entity_id=customers.id,
                relationship_type="many_to_one",
                join_condition=f"{source.table_name}.customer_id = customers.id",
                relationship_key=key,
                column_pairs=[{"from_column_id": foreign_key.id, "to_column_id": customer_id.id}],
                validation_status="valid",
            )
        )
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    assert metric is not None
    metric.name = "Sales to returns ratio by region"
    metric.definition = {
        "schema_version": 3,
        "metric": {
            "name": metric.name,
            "base_entity": "orders",
            "formula": {"function": "COUNT", "expression": "*"},
            "query_plan": {
                "stages": [
                    {"name": "sales", "base_entity": "orders", "joins": ["customers"],
                     "group_by": [{"name": "region", "expression": "customers.region", "column_id": region.id}],
                     "aggregates": [{"name": "total", "function": "SUM", "expression": "orders.amount"}]},
                    {"name": "refunds", "base_entity": "returns", "joins": ["customers"],
                     "group_by": [{"name": "region", "expression": "customers.region", "column_id": region.id}],
                     "aggregates": [{"name": "total", "function": "SUM", "expression": "returns.amount"}]},
                ],
                "output_expression": "sales.total / refunds.total",
            },
            "filters": [], "status": "approved",
        },
    }
    await async_session.commit()
    await async_session.execute(text('CREATE TABLE "orders" ("id" INTEGER, "amount" NUMERIC, "customer_id" INTEGER, "status" TEXT, "is_test" INTEGER)'))
    await async_session.execute(text('CREATE TABLE "customers" ("id" INTEGER, "region" TEXT)'))
    await async_session.execute(text('CREATE TABLE "returns" ("id" INTEGER, "amount" NUMERIC, "customer_id" INTEGER)'))
    await async_session.execute(text('INSERT INTO "customers" VALUES (1, \'north\'), (2, \'south\')'))
    await async_session.execute(text('INSERT INTO "orders" VALUES (1, 100, 1, \'completed\', 0), (2, 200, 2, \'completed\', 0)'))
    await async_session.execute(text('INSERT INTO "returns" VALUES (1, 50, 1)'))

    semantic_db = await async_session.get(SemanticDatabaseModel, db_id)
    for db_type, dialect in (("sqlite", "sqlite"), ("postgresql", "postgres"), ("mysql", "mysql")):
        semantic_db.db_type = db_type
        await async_session.flush()
        compiled = await SemanticQueryCompiler(async_session).compile(
            db_id, SemanticQuerySpec(metric_ids=[metric.id], dimensions=[DimensionSelection(column_id=region.id)])
        )
        assert "__metric_keys" in compiled.sql
        sqlglot.parse_one(compiled.sql, read=dialect)
    semantic_db.db_type = "sqlite"
    await async_session.flush()
    compiled = await SemanticQueryCompiler(async_session).compile(
        db_id, SemanticQuerySpec(metric_ids=[metric.id], dimensions=[DimensionSelection(column_id=region.id)])
    )
    result = await async_session.execute(text(compiled.sql), compiled.parameters)
    assert result.all() == [("north", 2.0), ("south", None)]


@pytest.mark.asyncio
async def test_three_table_plan_normalizes_agent_formula_and_compiles(async_session: AsyncSession) -> None:
    from src.models.metric_definition import MetricDefinition

    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    orders = await _table(async_session, db_id, "orders")
    order_customer = SemanticColumnModel(
        table_id=orders.id, column_name="customer_id", data_type="INTEGER", business_name="Customer ID"
    )
    customers = SemanticTableModel(
        db_id=db_id, table_name="customers", business_name="Customers", description="", primary_key_column="id"
    )
    items = SemanticTableModel(
        db_id=db_id, table_name="order_items", business_name="Order Items", description="", primary_key_column="id"
    )
    async_session.add_all([order_customer, customers, items])
    await async_session.flush()
    customer_id = SemanticColumnModel(
        table_id=customers.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
    )
    region = SemanticColumnModel(
        table_id=customers.id, column_name="region", data_type="TEXT", business_name="Region"
    )
    item_id = SemanticColumnModel(
        table_id=items.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
    )
    item_order = SemanticColumnModel(
        table_id=items.id, column_name="order_id", data_type="INTEGER", business_name="Order ID"
    )
    quantity = SemanticColumnModel(
        table_id=items.id, column_name="quantity", data_type="INTEGER", business_name="Quantity"
    )
    unit_price = SemanticColumnModel(
        table_id=items.id, column_name="unit_price", data_type="NUMERIC", business_name="Unit Price"
    )
    async_session.add_all([customer_id, region, item_id, item_order, quantity, unit_price])
    await async_session.flush()
    order_id = await _column(async_session, orders.id, "id")
    relationships = [
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=items.id,
            to_entity_id=orders.id,
            relationship_type="many_to_one",
            join_condition="order_items.order_id = orders.id",
            relationship_key="order_items_orders_three_table_test",
            column_pairs=[{"from_column_id": item_order.id, "to_column_id": order_id.id}],
            validation_status="valid",
        ),
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=orders.id,
            to_entity_id=customers.id,
            relationship_type="many_to_one",
            join_condition="orders.customer_id = customers.id",
            relationship_key="orders_customers_three_table_test",
            column_pairs=[{"from_column_id": order_customer.id, "to_column_id": customer_id.id}],
            validation_status="valid",
        ),
    ]
    async_session.add_all(relationships)
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    assert metric is not None
    metric.name = "Item revenue by customer region"
    metric.base_entity_id = items.id
    metric.definition = {
        "schema_version": 2,
        "metric": {
            "name": metric.name,
            "base_entity": "order_items",
            "formula": {"function": "SUM", "expression": "quantity * unit_price"},
            "query_plan": {
                "stages": [{
                    "name": "revenue_by_region",
                    "base_entity": "order_items",
                    "joins": ["orders", "customers"],
                    "group_by": [{"name": "region", "expression": "customers.region", "column_id": region.id}],
                    "aggregates": [{
                        "name": "total_revenue",
                        "function": "SUM",
                        "expression": "order_items.quantity * order_items.unit_price",
                    }],
                }],
                "output_expression": "revenue_by_region.total_revenue",
            },
            "filters": [],
            "status": "approved",
        },
    }
    await async_session.commit()

    compiled = await SemanticQueryCompiler(async_session).compile(
        db_id,
        SemanticQuerySpec(metric_ids=[metric.id], dimensions=[DimensionSelection(column_id=region.id)]),
    )

    normalized = MetricDefinition.model_validate(metric.definition)
    assert normalized.schema_version == 3
    assert normalized.metric.formula.function == "COUNT"
    assert normalized.metric.formula.expression == "*"
    assert all(table in compiled.sql for table in ('"order_items"', '"orders"', '"customers"'))
    assert "SUM(" in compiled.sql
    assert len(set(compiled.metadata["relationship_ids"])) == 2


@pytest.mark.asyncio
async def test_compiler_rejects_sum_over_boolean_column(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    assert metric is not None
    definition = dict(metric.definition)
    test_id = (await _column(async_session, metric.base_entity_id, "is_test")).id
    definition["metric"]["formula"]["expression"] = "is_test"
    definition["metric"]["formula"]["expression_ast"] = {"kind": "column", "column_id": test_id}
    metric.definition = definition
    await async_session.commit()

    with pytest.raises(SemanticCompileError) as error:
        await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric.id]))
    assert error.value.code == "METRIC_NEEDS_REVIEW"


@pytest.mark.asyncio
async def test_compiler_rejects_ast_mismatch(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    assert metric is not None
    definition = dict(metric.definition)
    id_id = (await _column(async_session, metric.base_entity_id, "id")).id
    definition["metric"]["formula"]["expression_ast"] = {"kind": "column", "column_id": id_id}
    metric.definition = definition
    await async_session.commit()

    with pytest.raises(SemanticCompileError) as error:
        await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric.id]))
    assert error.value.code == "METRIC_NEEDS_REVIEW"


async def _table(db: AsyncSession, db_id: int, name: str) -> SemanticTableModel:
    from sqlalchemy import select

    result = await db.execute(
        select(SemanticTableModel).where(SemanticTableModel.db_id == db_id, SemanticTableModel.table_name == name)
    )
    return result.scalar_one()


async def _column(db: AsyncSession, table_id: int, name: str) -> SemanticColumnModel:
    from sqlalchemy import select

    result = await db.execute(
        select(SemanticColumnModel).where(
            SemanticColumnModel.table_id == table_id,
            SemanticColumnModel.column_name == name,
        )
    )
    return result.scalar_one()

@pytest.mark.asyncio
async def test_plan_uses_stored_base_id_and_qualified_cross_schema_join(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    public = await _table(async_session, db_id, "orders")
    public.physical_schema = "public"
    archive = SemanticTableModel(
        db_id=db_id, table_name="orders", physical_schema="archive", business_name="Archived orders", description=""
    )
    customers = SemanticTableModel(
        db_id=db_id, table_name="customers", physical_schema="public", business_name="Customers", description=""
    )
    async_session.add_all([archive, customers])
    await async_session.flush()
    fk = SemanticColumnModel(
        table_id=archive.id, column_name="customer_id", data_type="INTEGER", business_name="Customer"
    )
    pk = SemanticColumnModel(table_id=customers.id, column_name="id", data_type="INTEGER", business_name="ID")
    async_session.add_all([fk, pk])
    await async_session.flush()
    async_session.add(
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=archive.id,
            to_entity_id=customers.id,
            relationship_type="many_to_one",
            join_condition="old",
            relationship_key="cross_schema",
            column_pairs=[{"from_column_id": fk.id, "to_column_id": pk.id}],
            validation_status="valid",
        )
    )
    metric = await async_session.get(SemanticMetricModel, metric_ids[0])
    metric.base_entity_id = archive.id
    metric.definition = {
        "schema_version": 3,
        "metric": {
            "name": "Archived",
            "base_entity": "orders",
            "base_entity_id": archive.id,
            "formula": {"function": "COUNT", "expression": "*"},
            "query_plan": {
                "stages": [
                    {
                        "name": "counts",
                        "base_entity": "orders",
                        "aggregates": [{"name": "n", "function": "COUNT", "expression": "*"}],
                    }
                ],
                "output_expression": "counts.n",
            },
            "filters": [],
            "status": "approved",
        },
    }
    await async_session.flush()
    compiler = SemanticQueryCompiler(async_session)
    await async_session.execute(text("ATTACH DATABASE ':memory:' AS archive"))
    await async_session.execute(text("ATTACH DATABASE ':memory:' AS public"))
    await async_session.execute(text('CREATE TABLE archive.orders (customer_id INTEGER)'))
    await async_session.execute(text('CREATE TABLE public.orders (customer_id INTEGER)'))
    await async_session.execute(text('CREATE TABLE public.customers (id INTEGER)'))
    await async_session.execute(text('INSERT INTO archive.orders VALUES (1), (1)'))
    await async_session.execute(text('INSERT INTO public.orders VALUES (1), (1), (1)'))
    await async_session.execute(text('INSERT INTO public.customers VALUES (1)'))
    result = await compiler.compile(db_id, SemanticQuerySpec(metric_ids=[metric.id]))
    assert 'FROM "archive"."orders"' in result.sql
    assert (await async_session.execute(text(result.sql), result.parameters)).scalar_one() == 2
    metric.definition = {
        **metric.definition,
        "metric": {
            **metric.definition["metric"],
            "query_plan": {
                "stages": [
                    {
                        "name": "counts",
                        "base_entity": "orders",
                        "joins": ["public.customers"],
                        "aggregates": [{"name": "n", "function": "COUNT", "expression": "*"}],
                    }
                ],
                "output_expression": "counts.n",
            },
        },
    }
    await async_session.flush()
    result = await compiler.compile(db_id, SemanticQuerySpec(metric_ids=[metric.id]))
    assert 'JOIN "public"."customers"' in result.sql
    assert '"archive"."orders"."customer_id" = "public"."customers"."id"' in result.sql
    assert (await async_session.execute(text(result.sql), result.parameters)).scalar_one() == 2
    filtered = await compiler.compile(db_id, SemanticQuerySpec(metric_ids=[metric.id], filters=[SemanticQueryFilter(column_id=fk.id, operator="eq", value=1)]))
    assert (await async_session.execute(text(filtered.sql), filtered.parameters)).scalar_one() == 2
    metric.base_entity_id = None
    metric.definition = {**metric.definition, "metric": {**metric.definition["metric"], "base_entity_id": None}}
    await async_session.flush()
    with pytest.raises(SemanticCompileError):
        await compiler.compile(db_id, SemanticQuerySpec(metric_ids=[metric.id]))

@pytest.mark.asyncio
async def test_simple_metric_rejects_join_with_same_bare_table_name(async_session: AsyncSession) -> None:
    db_id, metric_ids = await _seed_filtered_metrics(async_session)
    public = await _table(async_session, db_id, "orders")
    public.physical_schema = "public"
    archive = SemanticTableModel(db_id=db_id, table_name="orders", physical_schema="archive", business_name="Archive", description="")
    async_session.add(archive)
    await async_session.flush()
    left = await _column(async_session, public.id, "id")
    right = SemanticColumnModel(table_id=archive.id, column_name="id", data_type="INTEGER", business_name="ID")
    async_session.add(right)
    await async_session.flush()
    async_session.add(CanonicalRelationshipModel(connection_id=db_id, from_entity_id=public.id, to_entity_id=archive.id, relationship_type="many_to_one", join_condition="old", relationship_key="duplicate_names", column_pairs=[{"from_column_id": left.id, "to_column_id": right.id}], validation_status="valid"))
    await async_session.flush()
    with pytest.raises(SemanticCompileError) as error:
        await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric_ids[0]], dimensions=[DimensionSelection(column_id=right.id)]))
    assert error.value.code == "UNSAFE_JOIN"
    assert "ambiguous table names" in str(error.value)
