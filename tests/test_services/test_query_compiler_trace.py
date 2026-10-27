"""Contract tests for the versioned compile trace (issue 14)."""

import json
from copy import deepcopy

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    CanonicalRelationshipModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.schemas import (
    DimensionSelection,
    SemanticQueryCompileResponse,
    SemanticQueryFilter,
    SemanticQuerySpec,
)
from src.services.query_compiler import SemanticQueryCompiler
from src.services.query_compiler_trace import TRACE_SCHEMA_VERSION, CompileTraceBuilder
from src.services.semantic_compile_error import SemanticCompileError


def test_snapshot_has_schema_version_and_ordered_steps() -> None:
    builder = CompileTraceBuilder()
    builder.step("load_metadata")
    builder.step("validate_references")
    assert builder.snapshot() == {
        "schema_version": TRACE_SCHEMA_VERSION,
        "completed_steps": ["load_metadata", "validate_references"],
    }


def test_record_fields_appear_in_snapshot() -> None:
    builder = CompileTraceBuilder()
    builder.record(effective_limit=100, filters=[{"column_id": 1, "operator": "eq", "scope": "metric"}])
    snapshot = builder.snapshot()
    assert snapshot["effective_limit"] == 100
    assert snapshot["filters"] == [{"column_id": 1, "operator": "eq", "scope": "metric"}]


def test_snapshot_is_isolated_from_later_records() -> None:
    builder = CompileTraceBuilder()
    builder.step("load_metadata")
    first = builder.snapshot()
    builder.record(effective_limit=5)
    builder.step("resolve_joins")
    assert "effective_limit" not in first
    assert first["completed_steps"] == ["load_metadata"]


def test_completed_steps_property_exposes_tuple() -> None:
    builder = CompileTraceBuilder()
    builder.step("render_sql")
    assert builder.completed_steps == ("render_sql",)


async def _seed_single_table(db: AsyncSession) -> tuple[int, int, dict[str, int]]:
    """Seed orders + 1 approved v2 metric (version=3) with a status filter."""
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
    columns = {
        name: SemanticColumnModel(
            table_id=table.id,
            column_name=name,
            data_type=data_type,
            business_name=name,
            is_primary_key=name == "id",
            is_time_dimension=name == "created_at",
        )
        for name, data_type in [
            ("id", "INTEGER"),
            ("amount", "NUMERIC"),
            ("status", "TEXT"),
            ("created_at", "TIMESTAMP"),
        ]
    }
    db.add_all(columns.values())
    await db.flush()
    metric = SemanticMetricModel(
        db_id=semantic_db.id,
        created_by=1,
        name="Revenue completed",
        description="",
        sql_template="",
        source="ai",
        status="approved",
        base_entity_id=table.id,
        formula="",
        aggregation_type="SUM",
        version=3,
        definition={
            "schema_version": 2,
            "metric": {
                "name": "Revenue completed",
                "formula": {
                    "function": "SUM",
                    "expression": "amount",
                    "expression_ast": {"kind": "column", "column_id": columns["amount"].id},
                },
                "base_entity": "orders",
                "base_entity_id": table.id,
                "grain": {"column_ids": [columns["id"].id]},
                "filters": [
                    {"field": "status", "column_id": columns["status"].id, "operator": "eq", "value": "shipped"}
                ],
                "status": "approved",
                "confidence": "high",
                "excluded_notes": "",
            },
        },
    )
    db.add(metric)
    await db.commit()
    ids = {"orders": table.id, **{name: column.id for name, column in columns.items()}}
    return semantic_db.id, metric.id, ids


@pytest.mark.asyncio
async def test_single_table_success_trace_records_full_contract(async_session: AsyncSession) -> None:
    db_id, metric_id, ids = await _seed_single_table(async_session)
    query = SemanticQuerySpec(
        metric_ids=[metric_id],
        dimensions=[DimensionSelection(column_id=ids["created_at"], time_grain="month")],
        filters=[SemanticQueryFilter(column_id=ids["status"], operator="eq", value="secret-runtime")],
        limit=250,
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, query)

    trace = compiled.metadata["trace"]
    assert set(trace) == {
        "schema_version",
        "completed_steps",
        "plan_type",
        "metrics",
        "base_entity",
        "dimensions",
        "join_path",
        "filters",
        "effective_limit",
    }  # whitelist key — không key ngoài contract (đảm bảo không connection info / dữ liệu khác)
    assert trace["schema_version"] == 1
    assert trace["plan_type"] == "single_table"
    assert trace["metrics"] == [
        {"id": metric_id, "name": "Revenue completed", "version": 3, "grain_column_ids": [ids["id"]]}
    ]
    assert trace["base_entity"] == {"table_name": "orders", "table_id": ids["orders"]}
    assert trace["dimensions"] == [{"column_id": ids["created_at"], "time_grain": "month"}]
    assert trace["join_path"] == []
    assert trace["filters"] == [
        {"column_id": ids["status"], "operator": "eq", "scope": "metric"},
        {"column_id": ids["status"], "operator": "eq", "scope": "runtime"},
    ]
    assert trace["effective_limit"] == 250
    assert trace["completed_steps"] == [
        "load_metadata",
        "validate_references",
        "resolve_joins",
        "render_sql",
        "validate_guardrails",
    ]


@pytest.mark.asyncio
async def test_success_trace_never_contains_filter_values(async_session: AsyncSession) -> None:
    db_id, metric_id, ids = await _seed_single_table(async_session)
    query = SemanticQuerySpec(
        metric_ids=[metric_id],
        filters=[SemanticQueryFilter(column_id=ids["status"], operator="eq", value="secret-runtime")],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, query)
    dumped = json.dumps(compiled.metadata["trace"])
    assert "secret-runtime" not in dumped
    # giá trị filter của metric definition ("shipped", không dùng "completed" vì trùng key "completed_steps")
    assert "shipped" not in dumped
    assert "value" not in dumped


@pytest.mark.asyncio
async def test_legacy_arguments_clamp_effective_limit(async_session: AsyncSession) -> None:
    db_id, metric_id, _ = await _seed_single_table(async_session)
    compiled = await SemanticQueryCompiler(async_session).compile(
        db_id, metric_ids=[metric_id], dimension_ids=[], limit=5000
    )
    assert compiled.metadata["trace"]["effective_limit"] == 1000


@pytest.mark.asyncio
async def test_trace_join_path_matches_metadata_relationship_order(async_session: AsyncSession) -> None:
    db_id, metric_id, ids = await _seed_single_table(async_session)
    # seed customers(id PK, segment) + orders.customer_id FK + relationship many_to_one
    # (copy pattern from test_runtime_filter_adds_its_required_join, keep the relationship object)
    orders = await async_session.get(SemanticTableModel, ids["orders"])
    assert orders is not None
    customers = SemanticTableModel(
        db_id=db_id, table_name="customers", business_name="Khách hàng", description="", primary_key_column="id"
    )
    async_session.add(customers)
    await async_session.flush()
    customer_fk = SemanticColumnModel(
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
    async_session.add_all([customer_fk, customer_pk, segment])
    await async_session.flush()
    relationship = CanonicalRelationshipModel(
        connection_id=db_id,
        from_entity_id=orders.id,
        to_entity_id=customers.id,
        relationship_type="many_to_one",
        join_condition="orders.customer_id = customers.id",
        column_pairs=[{"from_column_id": customer_fk.id, "to_column_id": customer_pk.id}],
    )
    async_session.add(relationship)
    await async_session.commit()

    query = SemanticQuerySpec(
        metric_ids=[metric_id],
        dimensions=[DimensionSelection(column_id=segment.id)],
        filters=[SemanticQueryFilter(column_id=segment.id, operator="eq", value="enterprise")],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, query)

    trace = compiled.metadata["trace"]
    assert [hop["relationship_id"] for hop in trace["join_path"]] == compiled.metadata["relationship_ids"]
    assert trace["join_path"] == [{"relationship_id": relationship.id, "from_table": "orders", "to_table": "customers"}]
    # trace khớp đúng số JOIN trong SQL text (join được strip nên JOIN đứng sau "\n", không phải " ")
    assert compiled.sql.count("JOIN ") == len(trace["join_path"])


async def _seed_three_table_plan(db: AsyncSession) -> tuple[int, int, dict[str, int], dict[str, int]]:
    """Seed the 3-table plan metric copied from the v3 plan compile test."""
    semantic_db = SemanticDatabaseModel(
        created_by=1, display_name="Sales", db_type="sqlite", conn_url_enc="encrypted", status="draft"
    )
    db.add(semantic_db)
    await db.flush()
    orders = SemanticTableModel(
        db_id=semantic_db.id, table_name="orders", business_name="Đơn hàng", description="", primary_key_column="id"
    )
    customers = SemanticTableModel(
        db_id=semantic_db.id, table_name="customers", business_name="Customers", description="", primary_key_column="id"
    )
    items = SemanticTableModel(
        db_id=semantic_db.id,
        table_name="order_items",
        business_name="Order Items",
        description="",
        primary_key_column="id",
    )
    db.add_all([orders, customers, items])
    await db.flush()
    orders_columns = [
        SemanticColumnModel(
            table_id=orders.id,
            column_name=name,
            data_type=data_type,
            business_name=name,
            is_primary_key=name == "id",
        )
        for name, data_type in [("id", "INTEGER"), ("amount", "NUMERIC"), ("status", "TEXT"), ("is_test", "BOOLEAN")]
    ]
    order_customer = SemanticColumnModel(
        table_id=orders.id, column_name="customer_id", data_type="INTEGER", business_name="Customer ID"
    )
    customer_id = SemanticColumnModel(
        table_id=customers.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
    )
    region = SemanticColumnModel(table_id=customers.id, column_name="region", data_type="TEXT", business_name="Region")
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
    db.add_all([*orders_columns, order_customer, customer_id, region, item_id, item_order, quantity, unit_price])
    await db.flush()
    items_orders = CanonicalRelationshipModel(
        connection_id=semantic_db.id,
        from_entity_id=items.id,
        to_entity_id=orders.id,
        relationship_type="many_to_one",
        join_condition="order_items.order_id = orders.id",
        relationship_key="order_items_orders_three_table_test",
        column_pairs=[{"from_column_id": item_order.id, "to_column_id": orders_columns[0].id}],
        validation_status="valid",
    )
    orders_customers = CanonicalRelationshipModel(
        connection_id=semantic_db.id,
        from_entity_id=orders.id,
        to_entity_id=customers.id,
        relationship_type="many_to_one",
        join_condition="orders.customer_id = customers.id",
        relationship_key="orders_customers_three_table_test",
        column_pairs=[{"from_column_id": order_customer.id, "to_column_id": customer_id.id}],
        validation_status="valid",
    )
    metric = SemanticMetricModel(
        db_id=semantic_db.id,
        created_by=1,
        name="Item revenue by customer region",
        description="",
        sql_template="",
        source="ai",
        status="approved",
        base_entity_id=items.id,
        formula="",
        aggregation_type="SUM",
        definition={
            "schema_version": 2,
            "metric": {
                "name": "Item revenue by customer region",
                "base_entity": "order_items",
                "formula": {"function": "SUM", "expression": "quantity * unit_price"},
                "query_plan": {
                    "stages": [
                        {
                            "name": "revenue_by_region",
                            "base_entity": "order_items",
                            "joins": ["orders", "customers"],
                            "group_by": [{"name": "region", "expression": "customers.region", "column_id": region.id}],
                            "aggregates": [
                                {
                                    "name": "total_revenue",
                                    "function": "SUM",
                                    "expression": "order_items.quantity * order_items.unit_price",
                                }
                            ],
                        }
                    ],
                    "output_expression": "revenue_by_region.total_revenue",
                },
                "filters": [],
                "status": "approved",
            },
        },
    )
    db.add_all([items_orders, orders_customers, metric])
    await db.commit()
    ids = {"orders": orders.id, "customers": customers.id, "order_items": items.id, "region": region.id}
    rel_ids = {"items_orders": items_orders.id, "orders_customers": orders_customers.id}
    return semantic_db.id, metric.id, ids, rel_ids


@pytest.mark.asyncio
async def test_metric_plan_success_trace_records_stage_join_order(async_session: AsyncSession) -> None:
    db_id, metric_id, ids, rel_ids = await _seed_three_table_plan(async_session)
    compiled = await SemanticQueryCompiler(async_session).compile(
        db_id, SemanticQuerySpec(metric_ids=[metric_id], dimensions=[DimensionSelection(column_id=ids["region"])])
    )

    trace = compiled.metadata["trace"]
    assert set(trace) == {
        "schema_version",
        "completed_steps",
        "plan_type",
        "metrics",
        "base_entity",
        "dimensions",
        "join_path",
        "filters",
        "effective_limit",
    }
    assert trace["plan_type"] == "metric_plan"
    assert trace["metrics"] == [
        {"id": metric_id, "name": "Item revenue by customer region", "version": 1, "grain_column_ids": []}
    ]
    assert trace["base_entity"] == {"table_name": "order_items", "table_id": ids["order_items"]}
    assert trace["dimensions"] == [{"column_id": ids["region"], "time_grain": None}]
    assert trace["filters"] == []
    assert trace["effective_limit"] == 100
    assert trace["completed_steps"] == [
        "load_metadata",
        "validate_references",
        "resolve_joins",
        "render_sql",
        "validate_guardrails",
    ]
    assert [hop["relationship_id"] for hop in trace["join_path"]] == compiled.metadata["relationship_ids"]
    assert trace["join_path"] == [
        {"relationship_id": rel_ids["items_orders"], "from_table": "order_items", "to_table": "orders"},
        {"relationship_id": rel_ids["items_orders"], "from_table": "order_items", "to_table": "orders"},
        {"relationship_id": rel_ids["orders_customers"], "from_table": "order_items", "to_table": "customers"},
    ]


async def _seed_fanout(db: AsyncSession) -> tuple[int, int, dict[str, int]]:
    """Seed a customers-based COUNT metric reached from orders via many-to-one."""
    db_id, metric_id, ids = await _seed_single_table(db)
    customers = SemanticTableModel(
        db_id=db_id, table_name="customers", business_name="Khách hàng", description="", primary_key_column="id"
    )
    db.add(customers)
    await db.flush()
    customer_pk = SemanticColumnModel(
        table_id=customers.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
    )
    db.add(customer_pk)
    await db.flush()
    metric = await db.get(SemanticMetricModel, metric_id)
    assert metric is not None
    metric.base_entity_id = customers.id
    definition = deepcopy(metric.definition)
    definition["metric"]["base_entity"] = "customers"
    definition["metric"]["base_entity_id"] = customers.id
    definition["metric"]["formula"] = {
        "function": "COUNT",
        "expression": "*",
        "expression_ast": {"kind": "literal", "value": 1},
    }
    definition["metric"]["grain"] = {"column_ids": [customer_pk.id]}
    definition["metric"]["filters"] = []
    metric.definition = definition
    db.add(
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=ids["orders"],
            to_entity_id=customers.id,
            relationship_type="many_to_one",
            join_condition="orders.customer_id = customers.id",
            relationship_key="orders_customer",
            validation_status="valid",
        )
    )
    await db.commit()
    return db_id, metric_id, {**ids, "customers": customers.id}


@pytest.mark.asyncio
async def test_unsafe_fanout_error_carries_partial_trace(async_session: AsyncSession) -> None:
    db_id, metric_id, ids = await _seed_fanout(async_session)
    query = SemanticQuerySpec(metric_ids=[metric_id], dimensions=[DimensionSelection(column_id=ids["amount"])])
    with pytest.raises(SemanticCompileError) as error:
        await SemanticQueryCompiler(async_session).compile(db_id, query)

    exc = error.value
    assert exc.code == "UNSAFE_FANOUT"
    assert str(exc) == "Dimension requires a one-to-many join"
    assert exc.context["table_id"] == ids["orders"]  # context key cũ nguyên vẹn
    partial = exc.context["partial_trace"]
    assert partial["schema_version"] == 1
    assert partial["completed_steps"] == ["load_metadata", "validate_references"]
    assert partial["base_entity"] == {"table_name": "customers", "table_id": ids["customers"]}
    assert [item["id"] for item in partial["metrics"]] == [metric_id]
    assert "join_path" not in partial  # bước resolve_joins chưa hoàn thành
    json.dumps(exc.to_detail())  # error detail vẫn JSON-safe


@pytest.mark.asyncio
async def test_unknown_metric_error_has_no_partial_trace(async_session: AsyncSession) -> None:
    db_id, metric_id, _ = await _seed_single_table(async_session)
    with pytest.raises(SemanticCompileError) as error:
        await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[99999]))
    assert error.value.code == "UNKNOWN_REFERENCE"
    assert error.value.context == {"metric_ids": [99999]}


@pytest.mark.asyncio
async def test_partial_trace_never_contains_filter_values(async_session: AsyncSession) -> None:
    db_id, metric_id, ids = await _seed_fanout(async_session)
    query = SemanticQuerySpec(
        metric_ids=[metric_id],
        dimensions=[DimensionSelection(column_id=ids["amount"])],
        filters=[SemanticQueryFilter(column_id=ids["amount"], operator="gt", value="secret-runtime")],
    )
    with pytest.raises(SemanticCompileError) as error:
        await SemanticQueryCompiler(async_session).compile(db_id, query)
    dumped = json.dumps(error.value.context["partial_trace"])
    assert "secret-runtime" not in dumped
    assert "value" not in dumped


@pytest.mark.asyncio
async def test_compile_response_serializes_trace_through_api_contract(async_session: AsyncSession) -> None:
    db_id, metric_id, _ = await _seed_single_table(async_session)
    compiled = await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric_id]))
    response = SemanticQueryCompileResponse(
        sql=compiled.sql, parameters=compiled.parameters, metadata=compiled.metadata
    )
    payload = json.loads(response.model_dump_json())
    assert payload["metadata"]["trace"]["schema_version"] == 1
    assert payload["metadata"]["base_entity"] == "orders"  # key cũ không đổi


@pytest.mark.asyncio
async def test_render_failure_partial_trace_lists_last_completed_step(async_session: AsyncSession) -> None:
    db_id, metric_id, ids = await _seed_single_table(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric is not None
    definition = dict(metric.definition)
    definition["metric"]["formula"] = {
        "function": "SUM",
        "expression": "amount / id",
        "expression_ast": {
            "kind": "div",
            "children": [
                {"kind": "column", "column_id": ids["amount"]},
                {"kind": "column", "column_id": ids["id"]},
            ],
        },
    }
    metric.definition = definition
    await async_session.commit()

    with pytest.raises(SemanticCompileError) as error:
        await SemanticQueryCompiler(async_session).compile(db_id, SemanticQuerySpec(metric_ids=[metric_id]))

    assert error.value.code == "METRIC_NEEDS_REVIEW"
    partial = error.value.context["partial_trace"]
    assert partial["completed_steps"] == ["load_metadata", "validate_references", "resolve_joins"]
    assert partial["filters"] == [{"column_id": ids["status"], "operator": "eq", "scope": "metric"}]
    assert "join_path" in partial  # joins đã resolve trước render — có mặt và an toàn
    assert "render_sql" not in partial["completed_steps"]
