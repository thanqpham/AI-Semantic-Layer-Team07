"""Characterization tests pinning runtime filter scoping in multi-table metric plans."""

import copy
from typing import Any

import pytest
import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    CanonicalRelationshipModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.metric_definition import MetricPlanAggregate, MetricPlanStage
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.services.query_compiler import CompiledQuery, SemanticQueryCompiler
from src.services.query_compiler_plan import resolve_scoped_filter_stages
from src.services.semantic_compile_error import SemanticCompileError

_COLUMN_SPECS: dict[str, list[tuple[str, str]]] = {
    "orders": [
        ("id", "INTEGER"),
        ("amount", "NUMERIC"),
        ("status", "TEXT"),
        ("customer_id", "INTEGER"),
        ("created_at", "DATE"),
        ("coupon_code", "TEXT"),
    ],
    "customers": [("id", "INTEGER"), ("region", "TEXT")],
    "returns": [
        ("id", "INTEGER"),
        ("amount", "NUMERIC"),
        ("customer_id", "INTEGER"),
        ("reason", "TEXT"),
    ],
}


def _runtime(col_id: int, op: str, value: Any) -> SemanticQueryFilter:
    """Build a runtime filter against an approved semantic column."""
    return SemanticQueryFilter(column_id=col_id, operator=op, value=value)


async def _seed_semantic_tables(db: AsyncSession) -> dict[str, SemanticTableModel]:
    """Create the semantic database plus the orders, customers and returns tables."""
    semantic_db = SemanticDatabaseModel(
        created_by=1, display_name="Sales", db_type="sqlite", conn_url_enc="encrypted", status="draft"
    )
    db.add(semantic_db)
    await db.flush()
    tables = [
        SemanticTableModel(
            db_id=semantic_db.id,
            table_name=table_name,
            business_name=business_name,
            description="",
            primary_key_column="id",
        )
        for table_name, business_name in (
            ("orders", "Đơn hàng"),
            ("customers", "Khách hàng"),
            ("returns", "Trả hàng"),
        )
    ]
    db.add_all(tables)
    await db.flush()
    return {table.table_name: table for table in tables}


async def _seed_columns(
    db: AsyncSession, tables: dict[str, SemanticTableModel]
) -> dict[str, dict[str, SemanticColumnModel]]:
    """Register every physical column of the seeded tables."""
    columns: dict[str, dict[str, SemanticColumnModel]] = {}
    for table_name, specs in _COLUMN_SPECS.items():
        records = [
            SemanticColumnModel(
                table_id=tables[table_name].id,
                column_name=column_name,
                data_type=data_type,
                business_name=column_name,
                is_primary_key=column_name == "id",
                is_time_dimension=column_name == "created_at",
            )
            for column_name, data_type in specs
        ]
        db.add_all(records)
        await db.flush()
        columns[table_name] = {record.column_name: record for record in records}
    return columns


async def _seed_relationships(
    db: AsyncSession,
    db_id: int,
    tables: dict[str, SemanticTableModel],
    columns: dict[str, dict[str, SemanticColumnModel]],
) -> None:
    """Link orders and returns to customers through validated many_to_one joins."""
    customer_pk = columns["customers"]["id"]
    for table_name, key in (("orders", "orders_customers_plan_filter"), ("returns", "returns_customers_plan_filter")):
        db.add(
            CanonicalRelationshipModel(
                connection_id=db_id,
                from_entity_id=tables[table_name].id,
                to_entity_id=tables["customers"].id,
                relationship_type="many_to_one",
                join_condition=f"{table_name}.customer_id = customers.id",
                relationship_key=key,
                column_pairs=[
                    {"from_column_id": columns[table_name]["customer_id"].id, "to_column_id": customer_pk.id}
                ],
                validation_status="valid",
            )
        )
    await db.flush()


def _stage(name: str, base_entity: str, expression: str, region_id: int) -> dict[str, Any]:
    """Build one physical stage grouping regions and summing its fact amount."""
    return {
        "name": name,
        "base_entity": base_entity,
        "joins": ["customers"],
        "group_by": [{"name": "region", "expression": "customers.region", "column_id": region_id}],
        "aggregates": [{"name": "total", "function": "SUM", "expression": expression}],
    }


def _plan_definition(region_id: int) -> dict[str, Any]:
    """Build the two-stage sales/refunds ratio metric definition."""
    return {
        "schema_version": 3,
        "metric": {
            "name": "Sales to returns ratio by region",
            "base_entity": "orders",
            "formula": {"function": "SUM", "expression": "orders.amount"},
            "query_plan": {
                "stages": [
                    _stage("sales", "orders", "orders.amount", region_id),
                    _stage("refunds", "returns", "returns.amount", region_id),
                ],
                "output_expression": "sales.total / refunds.total",
            },
            "filters": [],
            "status": "approved",
        },
    }


async def _seed_plan_metric(
    db: AsyncSession,
    db_id: int,
    tables: dict[str, SemanticTableModel],
    columns: dict[str, dict[str, SemanticColumnModel]],
) -> SemanticMetricModel:
    """Create the approved schema_version 3 metric carrying the query plan."""
    region_id = columns["customers"]["region"].id
    metric = SemanticMetricModel(
        db_id=db_id,
        created_by=1,
        name="Sales to returns ratio by region",
        description="",
        sql_template="",
        source="ai",
        status="approved",
        base_entity_id=tables["orders"].id,
        formula="",
        aggregation_type="SUM",
        definition=_plan_definition(region_id),
    )
    db.add(metric)
    await db.flush()
    return metric


async def _seed_physical_tables(db: AsyncSession) -> None:
    """Create the physical SQLite tables and rows backing both plan stages."""
    await db.execute(
        text(
            'CREATE TABLE "orders" ("id" INTEGER, "amount" NUMERIC, "status" TEXT, '
            '"customer_id" INTEGER, "created_at" DATE, "coupon_code" TEXT)'
        )
    )
    await db.execute(text('CREATE TABLE "customers" ("id" INTEGER, "region" TEXT)'))
    await db.execute(
        text('CREATE TABLE "returns" ("id" INTEGER, "amount" NUMERIC, "customer_id" INTEGER, "reason" TEXT)')
    )
    await db.execute(text("INSERT INTO \"customers\" VALUES (1, 'north'), (2, 'south')"))
    await db.execute(
        text(
            'INSERT INTO "orders" VALUES '
            "(1, 100, 'completed', 1, '2026-01-05', 'SAVE10'), "
            "(2, 200, 'cancelled', 2, '2026-02-10', NULL), "
            "(3, 50, 'completed', 2, '2026-03-15', NULL)"
        )
    )
    await db.execute(text("INSERT INTO \"returns\" VALUES (1, 50, 1, 'damaged'), (2, 30, 2, 'wrong_item')"))


async def _seed_multi_fact_plan(db: AsyncSession) -> tuple[int, int, dict[str, SemanticColumnModel]]:
    """Seed semantic metadata, metric plan and physical data for plan filter tests."""
    tables = await _seed_semantic_tables(db)
    db_id = tables["orders"].db_id
    columns = await _seed_columns(db, tables)
    await _seed_relationships(db, db_id, tables, columns)
    metric = await _seed_plan_metric(db, db_id, tables, columns)
    await db.commit()
    await _seed_physical_tables(db)
    cols = {
        "status": columns["orders"]["status"],
        "amount": columns["orders"]["amount"],
        "created_at": columns["orders"]["created_at"],
        "coupon_code": columns["orders"]["coupon_code"],
        "region": columns["customers"]["region"],
        "reason": columns["returns"]["reason"],
    }
    return db_id, metric.id, cols


@pytest.mark.asyncio
async def test_shared_stage_runtime_filter_still_applies_to_every_stage(async_session: AsyncSession) -> None:
    """Runtime filters whose table is present in every stage are pushed into each stage CTE."""
    db_id, metric_id, cols = await _seed_multi_fact_plan(async_session)
    compiled = await SemanticQueryCompiler(async_session).compile(
        db_id,
        SemanticQuerySpec(
            metric_ids=[metric_id],
            dimensions=[DimensionSelection(column_id=cols["region"].id)],
            filters=[_runtime(cols["region"].id, "eq", "north")],
        ),
    )
    # predicate có trong CỦA HAI stage CTE
    assert compiled.sql.count("WHERE") == 2
    assert "north" not in compiled.sql  # bound parameter
    assert "north" in [str(v) for v in compiled.parameters.values()]
    result = await async_session.execute(text(compiled.sql), compiled.parameters)
    assert result.all() == [("north", 2.0)]  # south bị lọc khỏi keys UNION


async def _compile_ratio_by_region(
    session: AsyncSession, db_id: int, metric_id: int, region_id: int, filters: list[SemanticQueryFilter]
) -> CompiledQuery:
    """Compile the seeded ratio metric grouped by region with optional runtime filters."""
    return await SemanticQueryCompiler(session).compile(
        db_id,
        SemanticQuerySpec(
            metric_ids=[metric_id],
            dimensions=[DimensionSelection(column_id=region_id)],
            filters=filters,
        ),
    )


def _assert_status_filter_only_in_sales_cte(compiled: CompiledQuery) -> None:
    """Assert the status predicate exists only inside the sales CTE as a bound parameter."""
    assert compiled.sql.count("WHERE") == 1  # chỉ sales CTE
    sales_cte = compiled.sql.split('refunds" AS')[0]  # phần CTE sales đứng trước
    assert '"orders"."status"' in sales_cte and "WHERE" in sales_cte
    refunds_part = compiled.sql.split('refunds" AS')[1]
    assert "WHERE" not in refunds_part
    assert "completed" not in compiled.sql  # bound parameter


@pytest.mark.asyncio
async def test_single_stage_runtime_filter_applies_only_to_its_stage(async_session: AsyncSession) -> None:
    """A runtime filter whose table sits in exactly one stage is pushed only into that stage."""
    db_id, metric_id, cols = await _seed_multi_fact_plan(async_session)
    runtime = [_runtime(cols["status"].id, "eq", "completed")]  # status chỉ thuộc stage sales
    compiled = await _compile_ratio_by_region(async_session, db_id, metric_id, cols["region"].id, runtime)
    _assert_status_filter_only_in_sales_cte(compiled)
    result = await async_session.execute(text(compiled.sql), compiled.parameters)
    assert result.all() == [("north", 2.0), ("south", pytest.approx(50 / 30))]
    # unfiltered sẽ là south = 250/30 ≈ 8.33 — filter chỉ ăn vào sales side
    semantic_db = await async_session.get(SemanticDatabaseModel, db_id)
    for db_type, dialect in (("sqlite", "sqlite"), ("postgresql", "postgres"), ("mysql", "mysql")):
        semantic_db.db_type = db_type
        await async_session.flush()
        compiled_dialect = await _compile_ratio_by_region(async_session, db_id, metric_id, cols["region"].id, runtime)
        sqlglot.parse_one(compiled_dialect.sql, read=dialect)
    semantic_db.db_type = "sqlite"
    await async_session.flush()


@pytest.mark.asyncio
async def test_single_stage_definition_filter_scopes_to_own_stage(async_session: AsyncSession) -> None:
    """A metric-level filter whose column belongs to one stage scopes to that stage only."""
    db_id, metric_id, cols = await _seed_multi_fact_plan(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric is not None
    definition = copy.deepcopy(metric.definition)
    definition["metric"]["filters"] = [
        {"field": "status", "column_id": cols["status"].id, "operator": "eq", "value": "completed"}
    ]
    metric.definition = definition
    await async_session.commit()
    compiled = await _compile_ratio_by_region(async_session, db_id, metric_id, cols["region"].id, [])
    _assert_status_filter_only_in_sales_cte(compiled)
    result = await async_session.execute(text(compiled.sql), compiled.parameters)
    assert result.all() == [("north", 2.0), ("south", pytest.approx(50 / 30))]


# ---------------------------------------------------------------------------
# Unit tests: resolve_scoped_filter_stages placement matrix (no database)
# ---------------------------------------------------------------------------

_UNIT_BY_ID: dict[int, tuple[str, str, int, str]] = {
    101: ("customers", "region", 101, "TEXT"),
    102: ("orders", "status", 102, "TEXT"),
    103: ("shipments", "carrier", 103, "TEXT"),
}


def _physical_stage(name: str, base_entity: str) -> MetricPlanStage:
    """Build a minimal physical plan stage summing its base entity amount."""
    return MetricPlanStage(
        name=name,
        base_entity=base_entity,
        aggregates=[MetricPlanAggregate(name="total", function="SUM", expression=f"{base_entity}.amount")],
    )


def _derived_stage(name: str, source_stage: str) -> MetricPlanStage:
    """Build a minimal derived stage rolling up one prior stage output."""
    return MetricPlanStage(
        name=name,
        source_stage=source_stage,
        aggregates=[MetricPlanAggregate(name="grand", function="SUM", expression=f"{source_stage}.total")],
    )


def _unit_stages(with_exchanges: bool = False) -> list[MetricPlanStage]:
    """Return physical sales/refunds stages, an optional exchanges stage, and a derived roll-up."""
    physical = [_physical_stage("sales", "orders"), _physical_stage("refunds", "returns")]
    if with_exchanges:
        physical.append(_physical_stage("exchanges", "exchange_orders"))
    return [*physical, _derived_stage("ratio", "sales")]


def _unit_stage_tables(refunds_joins_customers: bool = True, with_exchanges: bool = False) -> dict[str, set[str]]:
    """Map every stage to its source tables the way _compile_plan does."""
    tables = {"sales": {"orders", "customers"}, "ratio": {"orders", "customers"}}
    tables["refunds"] = {"returns", "customers"} if refunds_joins_customers else {"returns"}
    if with_exchanges:
        tables["exchanges"] = {"exchange_orders", "customers"}
    return tables


@pytest.mark.parametrize(
    ("column_id", "expected_stages"),
    [
        pytest.param(101, ["sales", "refunds"], id="all_stages"),
        pytest.param(102, ["sales"], id="exactly_one_stage"),
    ],
)
def test_resolve_scoped_filter_stages_returns_matching_physical_stages(
    column_id: int, expected_stages: list[str]
) -> None:
    """A column resolved in one or in every physical stage is scoped to those stages."""
    members, resolved = resolve_scoped_filter_stages(column_id, _unit_stages(), _unit_stage_tables(), _UNIT_BY_ID)
    assert [stage.name for stage in members] == expected_stages
    assert resolved == _UNIT_BY_ID[column_id]


@pytest.mark.parametrize(
    ("column_id", "refunds_joins_customers", "with_exchanges", "reason", "stage_names"),
    [
        # Partial coverage needs 3 physical stages: customers sits in 2 of 3 stages.
        pytest.param(101, False, True, "partial_stage_coverage", ["sales", "exchanges"], id="partial_stage_coverage"),
        pytest.param(103, True, False, "not_in_plan", None, id="not_in_plan"),
        pytest.param(999, True, False, "unknown_column", None, id="unknown_column"),
        pytest.param(None, True, False, "unresolved_lineage", None, id="unresolved_lineage"),
    ],
)
def test_resolve_scoped_filter_stages_rejects_ambiguous_placement(
    column_id: int | None,
    refunds_joins_customers: bool,
    with_exchanges: bool,
    reason: str,
    stage_names: list[str] | None,
) -> None:
    """Placement that is neither exactly one stage nor every stage raises a compile error."""
    with pytest.raises(SemanticCompileError) as excinfo:
        resolve_scoped_filter_stages(
            column_id,
            _unit_stages(with_exchanges),
            _unit_stage_tables(refunds_joins_customers, with_exchanges),
            _UNIT_BY_ID,
        )
    assert excinfo.value.code == "UNSUPPORTED_PLAN_FILTER"
    assert excinfo.value.context["column_id"] == column_id
    assert excinfo.value.context["reason"] == reason
    # context chỉ chứa column_id/reason (và stage_names khi có) — không chứa filter value
    assert not excinfo.value.context.keys() - {"column_id", "reason", "stage_names"}
    if stage_names is None:
        assert "stage_names" not in excinfo.value.context
    else:
        assert excinfo.value.context["stage_names"] == stage_names


# --- End-to-end rejects: ambiguous placement raises typed errors, never SQL ---


async def _seed_extra_column(
    db: AsyncSession, db_id: int, table_name: str, column_name: str, data_type: str = "TEXT"
) -> SemanticColumnModel:
    """Register a semantic table and column that no metric plan stage covers."""
    table = SemanticTableModel(db_id=db_id, table_name=table_name, business_name=table_name, primary_key_column="id")
    db.add(table)
    await db.flush()
    column = SemanticColumnModel(
        table_id=table.id, column_name=column_name, data_type=data_type, business_name=column_name
    )
    db.add(column)
    await db.flush()
    return column


def _decoy_tickets_stage(priority_id: int) -> dict[str, Any]:
    """Build a third stage whose grain never appears in the output expression."""
    return {
        "name": "tickets",
        "base_entity": "tickets",
        "group_by": [{"name": "priority", "expression": "tickets.priority", "column_id": priority_id}],
        "aggregates": [{"name": "count", "function": "COUNT", "expression": "*"}],
    }


@pytest.mark.asyncio
async def test_partial_stage_coverage_filter_is_rejected(async_session: AsyncSession) -> None:
    """A filter covering only 2 of 3 stages is rejected before grain checks or render."""
    db_id, metric_id, cols = await _seed_multi_fact_plan(async_session)
    priority = await _seed_extra_column(async_session, db_id, "tickets", "priority")
    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric is not None
    definition = copy.deepcopy(metric.definition)
    # tickets groups a grain absent from the output terminals: only placement rejects it.
    definition["metric"]["query_plan"]["stages"].append(_decoy_tickets_stage(priority.id))
    metric.definition = definition
    await async_session.commit()
    runtime = [_runtime(cols["region"].id, "eq", "north")]  # customers sits in sales+refunds only
    with pytest.raises(SemanticCompileError) as excinfo:
        await _compile_ratio_by_region(async_session, db_id, metric_id, cols["region"].id, runtime)
    assert excinfo.value.code == "UNSUPPORTED_PLAN_FILTER"
    assert excinfo.value.context["reason"] == "partial_stage_coverage"
    assert excinfo.value.context["stage_names"] == ["sales", "refunds"]
    assert "north" not in str(excinfo.value.context)  # no filter value leaks into context


@pytest.mark.asyncio
async def test_filter_column_outside_plan_is_rejected(async_session: AsyncSession) -> None:
    """A runtime filter on a column no stage covers is rejected as not_in_plan."""
    db_id, metric_id, cols = await _seed_multi_fact_plan(async_session)
    carrier = await _seed_extra_column(async_session, db_id, "shipments", "carrier")
    runtime = [_runtime(carrier.id, "eq", "fedex")]
    with pytest.raises(SemanticCompileError) as excinfo:
        await _compile_ratio_by_region(async_session, db_id, metric_id, cols["region"].id, runtime)
    assert excinfo.value.code == "UNSUPPORTED_PLAN_FILTER"
    assert excinfo.value.context["reason"] == "not_in_plan"
    assert "stage_names" not in excinfo.value.context


@pytest.mark.asyncio
async def test_filter_without_column_id_is_rejected_without_having(async_session: AsyncSession) -> None:
    """A metric filter lacking a column_id is rejected before any SQL is rendered."""
    db_id, metric_id, cols = await _seed_multi_fact_plan(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric is not None
    definition = copy.deepcopy(metric.definition)
    definition["metric"]["filters"] = [{"field": "status", "column_id": None, "operator": "eq", "value": "completed"}]
    metric.definition = definition
    await async_session.commit()
    with pytest.raises(SemanticCompileError) as excinfo:
        await _compile_ratio_by_region(async_session, db_id, metric_id, cols["region"].id, [])
    assert excinfo.value.code == "UNSUPPORTED_PLAN_FILTER"
    assert excinfo.value.context["reason"] == "unresolved_lineage"
    if "partial_trace" in excinfo.value.context:  # trace presence is issue-2 territory
        assert "render_sql" not in excinfo.value.context["partial_trace"]["completed_steps"]


@pytest.mark.asyncio
async def test_runtime_filter_unknown_column_id_is_unknown_reference(async_session: AsyncSession) -> None:
    """A runtime filter on a missing column fails reference loading before placement."""
    db_id, metric_id, cols = await _seed_multi_fact_plan(async_session)
    runtime = [_runtime(999999, "eq", "x")]
    with pytest.raises(SemanticCompileError) as excinfo:
        await _compile_ratio_by_region(async_session, db_id, metric_id, cols["region"].id, runtime)
    assert excinfo.value.code == "UNKNOWN_REFERENCE"
