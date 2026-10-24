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
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.services.query_compiler import SemanticQueryCompiler
from src.services.semantic_compile_error import SemanticCompileError


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
