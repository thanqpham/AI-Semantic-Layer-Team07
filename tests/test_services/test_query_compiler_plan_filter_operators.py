"""Operator battery, date binding, grain and guardrails for stage-scoped plan filters."""

import re
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import SemanticMetricModel
from src.models.metric_definition import MetricDefinition
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.services.query_compiler import CompiledQuery, SemanticQueryCompiler, validate_read_only
from src.services.query_compiler_plan import compile_plan_sql
from src.services.query_execution import _normalize_parameters
from src.services.semantic_compile_error import SemanticCompileError
from tests.test_services.test_query_compiler_plan_filters import _runtime, _seed_multi_fact_plan


async def _compile_ratio(
    db: AsyncSession,
    db_id: int,
    metric_id: int,
    region_id: int,
    filters: list[SemanticQueryFilter],
) -> CompiledQuery:
    """Compile the seeded sales/refunds ratio metric grouped by region."""
    return await SemanticQueryCompiler(db).compile(
        db_id,
        SemanticQuerySpec(
            metric_ids=[metric_id],
            dimensions=[DimensionSelection(column_id=region_id)],
            filters=filters,
        ),
    )


async def _compile_with_filter(db: AsyncSession, column_key: str, operator: str, value: Any) -> CompiledQuery:
    """Seed the multi-fact plan and compile it with one runtime filter on an orders column."""
    db_id, metric_id, cols = await _seed_multi_fact_plan(db)
    runtime = [_runtime(cols[column_key].id, operator, value)]
    return await _compile_ratio(db, db_id, metric_id, cols["region"].id, runtime)


async def _rows(db: AsyncSession, compiled: CompiledQuery) -> list[tuple[Any, ...]]:
    """Execute a compiled plan query with its bound parameters and return all rows."""
    result = await db.execute(text(compiled.sql), _normalize_parameters(compiled.parameters, "sqlite"))
    return list(result.all())


def _group_by_lines(sql: str) -> list[str]:
    """Return every GROUP BY clause (to end of line) in stage order."""
    return re.findall(r"GROUP BY[^\n]*", sql)


def _bound_strings(compiled: CompiledQuery) -> list[str]:
    """Return the bound parameter values rendered as strings."""
    return [str(value) for value in compiled.parameters.values()]


@pytest.mark.asyncio
async def test_eq_operator(async_session: AsyncSession) -> None:
    """status eq 'completed' narrows only the sales side and stays a bound parameter."""
    compiled = await _compile_with_filter(async_session, "status", "eq", "completed")
    assert await _rows(async_session, compiled) == [("north", 2.0), ("south", pytest.approx(50 / 30))]
    assert "completed" not in compiled.sql  # value never embedded as a literal
    assert "completed" in _bound_strings(compiled)


@pytest.mark.asyncio
async def test_range_operator(async_session: AsyncSession) -> None:
    """amount gte 60 keeps orders 1 and 2 in the sales stage only."""
    compiled = await _compile_with_filter(async_session, "amount", "gte", 60)
    assert await _rows(async_session, compiled) == [("north", 2.0), ("south", pytest.approx(200 / 30))]


@pytest.mark.asyncio
async def test_in_operator(async_session: AsyncSession) -> None:
    """status in [completed, cancelled] keeps every order and binds one parameter per member."""
    compiled = await _compile_with_filter(async_session, "status", "in", ["completed", "cancelled"])
    assert await _rows(async_session, compiled) == [("north", 2.0), ("south", pytest.approx(250 / 30))]
    assert len(compiled.parameters) == 2  # exactly the two IN members
    assert {"completed", "cancelled"} == set(_bound_strings(compiled))


@pytest.mark.asyncio
async def test_not_in_operator(async_session: AsyncSession) -> None:
    """status not_in [completed] drops every north order, leaving a NULL ratio row."""
    compiled = await _compile_with_filter(async_session, "status", "not_in", ["completed"])
    assert await _rows(async_session, compiled) == [("north", None), ("south", pytest.approx(200 / 30))]


@pytest.mark.asyncio
async def test_null_checks(async_session: AsyncSession) -> None:
    """coupon_code is_null keeps only the coupon-less orders 2 and 3 (both south)."""
    compiled = await _compile_with_filter(async_session, "coupon_code", "is_null", None)
    assert await _rows(async_session, compiled) == [("north", None), ("south", pytest.approx(250 / 30))]


@pytest.mark.asyncio
async def test_date_filter_binds_date_object(async_session: AsyncSession) -> None:
    """created_at gte binds a datetime.date via _normalize_value and hides the ISO string."""
    compiled = await _compile_with_filter(async_session, "created_at", "gte", "2026-02-01")
    assert await _rows(async_session, compiled) == [("north", None), ("south", pytest.approx(250 / 30))]
    assert date(2026, 2, 1) in compiled.parameters.values()
    assert "2026-02-01" not in compiled.sql  # value never embedded as a literal


@pytest.mark.asyncio
async def test_filter_does_not_change_grouping_grain(async_session: AsyncSession) -> None:
    """A single-stage filter never alters the declared GROUP BY grain of any stage CTE."""
    db_id, metric_id, cols = await _seed_multi_fact_plan(async_session)
    region_id = cols["region"].id
    runtime = [_runtime(cols["status"].id, "eq", "completed")]
    with_filter = await _compile_ratio(async_session, db_id, metric_id, region_id, runtime)
    without_filter = await _compile_ratio(async_session, db_id, metric_id, region_id, [])
    baseline = _group_by_lines(without_filter.sql)
    assert len(baseline) == 2  # one GROUP BY per stage CTE, in stage order
    assert _group_by_lines(with_filter.sql) == baseline


@pytest.mark.asyncio
async def test_single_stage_filter_sql_is_read_only(async_session: AsyncSession) -> None:
    """SQL carrying a single-stage filter still passes the explicit read-only guardrail."""
    compiled = await _compile_with_filter(async_session, "status", "eq", "completed")
    assert validate_read_only(compiled.sql, "sqlite") is True


# Guards the compile_plan_sql contract itself; placed here (not _plan_filters.py) because of the file line cap.
@pytest.mark.asyncio
async def test_compile_plan_sql_rejects_unresolved_runtime_filters(async_session: AsyncSession) -> None:
    """Passing unresolved runtime_filters to compile_plan_sql fails closed with a typed error."""
    _, metric_id, cols = await _seed_multi_fact_plan(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric is not None
    plan = MetricDefinition.model_validate(metric.definition).metric.query_plan
    runtime = [_runtime(cols["status"].id, "eq", "completed")]
    with pytest.raises(SemanticCompileError) as excinfo:
        compile_plan_sql(plan, metric_id, "sqlite", {}, {}, {}, [], {}, runtime, 100, {})
    assert excinfo.value.code == "UNSUPPORTED_PLAN_FILTER"
    assert excinfo.value.context["reason"] == "unresolved_lineage"
    assert excinfo.value.context["column_id"] is None
    assert "completed" not in str(excinfo.value.context)  # no filter value leaks into context
