"""Orchestrate semantic metadata preparation and SQL rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import SemanticMetricModel, SemanticTableModel
from src.models.metric_definition import MetricDefinition, MetricQueryPlan
from src.models.schemas import SemanticQuerySpec
from src.services.query_compiler_metadata import QueryCompilerMetadata
from src.services.query_compiler_plan import compile_plan_sql
from src.services.query_compiler_sql import (
    _assemble_sql,
    _dimension_expressions,
    _fixed_predicates,
    _metric_expressions,
    _residual_filters,
    _shared_filters,
    validate_read_only,
)
from src.services.query_compiler_trace import CompileTraceBuilder, record_loaded_trace, trace_filters, trace_join_path
from src.services.query_compiler_types import CompiledQuery
from src.services.query_compiler_validation import (
    apply_time_grains,
    canonical_definitions,
    validate_definition_asts,
)
from src.services.semantic_compile_error import SemanticCompileError


@dataclass(frozen=True)
class SimpleMetricCompileContext:
    """Validated metadata ready for the simple-metric SQL renderer."""

    dialect: str
    metrics: list[SemanticMetricModel]
    definitions: list[MetricDefinition]
    base: SemanticTableModel
    base_columns: dict[int, tuple[str, str]]
    dimensions: list[dict[str, Any]]
    joins: list[dict[str, Any]]
    runtime_filters: list[dict[str, Any]]
    limit: int
    order_by: str | None


@dataclass(frozen=True)
class MetricPlanCompileContext:
    """Resolved metadata ready for the metric-plan SQL renderer."""

    plan: MetricQueryPlan
    metric: SemanticMetricModel
    dialect: str
    tables: dict[str, SemanticTableModel]
    columns: dict[str, dict[str, tuple[str, int, str]]]
    join_paths: dict[tuple[str, str], list[dict[str, str]]]
    dimensions: list[dict[str, Any]]
    dimension_grains: dict[int, str]
    limit: int
    order_by: str | None


class QueryCompileOrchestrator:
    """Load and validate semantic metadata before selecting a SQL renderer."""

    def __init__(self, db: AsyncSession) -> None:
        self._metadata = QueryCompilerMetadata(db)

    async def compile(self, connection_id: int, spec: SemanticQuerySpec, trace: CompileTraceBuilder) -> CompiledQuery:
        dialect = await self._metadata.load_dialect(connection_id)
        metrics = await self._metadata.load_metrics(connection_id, spec.metric_ids)
        definitions = canonical_definitions(metrics)
        record_loaded_trace(trace, metrics, definitions, spec.limit)
        if any(item.metric.query_plan is not None for item in definitions):
            if len(definitions) != 1 or definitions[0].metric.query_plan is None:
                raise SemanticCompileError(
                    "INCOMPATIBLE_QUERY_PLAN", "Multi-table plans must be queried one metric at a time"
                )
            trace.record(plan_type="metric_plan")
            plan_context = await self._prepare_metric_plan(
                connection_id, spec, metrics[0], definitions[0], dialect, trace
            )
            return self._render_metric_plan(plan_context, trace)
        trace.record(plan_type="single_table")
        context = await self._prepare_simple_metric(connection_id, spec, metrics, definitions, dialect, trace)
        return self._render_simple_metric(context, trace)

    async def _prepare_simple_metric(
        self,
        connection_id: int,
        spec: SemanticQuerySpec,
        metrics: list[SemanticMetricModel],
        definitions: list[MetricDefinition],
        dialect: str,
        trace: CompileTraceBuilder,
    ) -> SimpleMetricCompileContext:
        base_name = self._metadata.require_same_base(definitions)
        base, table_by_id = await self._load_base_tables(connection_id, base_name, metrics, definitions)
        dimensions = await self._metadata.load_dimensions(connection_id, [item.column_id for item in spec.dimensions])
        base_columns = await self._metadata.load_base_columns(base.id)
        validate_definition_asts(definitions, base_columns)
        apply_time_grains(dimensions, spec.dimensions)
        trace.record(base_entity={"table_name": base.table_name, "table_id": base.id})
        trace.step("validate_references")
        dimensions, joins, runtime_filters = await self._prepare_simple_metric_selections(
            connection_id, spec, dimensions, base, table_by_id
        )
        trace.record(join_path=trace_join_path(base.table_name, joins))
        trace.step("resolve_joins")
        trace.record(
            dimensions=[{"column_id": item["column_id"], "time_grain": item["time_grain"]} for item in dimensions],
            filters=trace_filters(definitions, runtime_filters),
        )
        return SimpleMetricCompileContext(
            dialect=dialect,
            metrics=metrics,
            definitions=definitions,
            base=base,
            base_columns=base_columns,
            dimensions=dimensions,
            joins=joins,
            runtime_filters=runtime_filters,
            limit=spec.limit,
            order_by=spec.order_by,
        )

    async def _load_base_tables(
        self,
        connection_id: int,
        base_name: str,
        metrics: list[SemanticMetricModel],
        definitions: list[MetricDefinition],
    ) -> tuple[SemanticTableModel, dict[int, SemanticTableModel]]:
        tables = await self._metadata.load_tables(connection_id)
        table_by_id = {table.id: table for table in tables}
        bases = []
        for metric, definition in zip(metrics, definitions, strict=True):
            ids = {value for value in (metric.base_entity_id, definition.metric.base_entity_id) if value is not None}
            matches = [
                table
                for table in tables
                if base_name.casefold()
                in {table.table_name.casefold(), f"{table.physical_schema}.{table.table_name}".casefold()}
                and (not ids or table.id in ids)
            ]
            if len(ids) > 1 or len(matches) != 1:
                raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric base entity is ambiguous or inconsistent")
            bases.append(matches[0])
        if len({base.id for base in bases}) != 1:
            raise SemanticCompileError("INCOMPATIBLE_BASE_ENTITY", "All selected metrics must use the same base entity")
        return bases[0], table_by_id

    async def _prepare_simple_metric_selections(
        self,
        connection_id: int,
        spec: SemanticQuerySpec,
        dimensions: list[dict[str, Any]],
        base: SemanticTableModel,
        table_by_id: dict[int, SemanticTableModel],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        runtime_filters = await self._metadata.load_runtime_filters(connection_id, spec.filters)
        joins = await self._metadata.resolve_joins(connection_id, base, dimensions + runtime_filters, table_by_id)
        return dimensions, joins, runtime_filters

    def _render_simple_metric(self, context: SimpleMetricCompileContext, trace: CompileTraceBuilder) -> CompiledQuery:
        parameters: dict[str, Any] = {}
        names = {cid: name for cid, (name, _) in context.base_columns.items()}
        types = {cid: dt for cid, (_, dt) in context.base_columns.items()}
        dimensions_sql, group_sql = _dimension_expressions(context.dimensions, context.dialect)
        shared = _shared_filters(context.definitions)
        residuals = [_residual_filters(item, shared) for item in context.definitions]
        fixed = _fixed_predicates(shared, names, types, context.base.table_name, context.dialect, parameters)
        metrics_sql = _metric_expressions(
            context.metrics, context.definitions, context.base, names, types, context.dialect, parameters, residuals
        )
        sql = _assemble_sql(
            dimensions_sql + metrics_sql,
            context.base,
            context.joins,
            context.runtime_filters,
            group_sql,
            context.dialect,
            parameters,
            context.limit,
            fixed,
            context.order_by,
        )
        trace.step("render_sql")
        validate_read_only(sql)
        trace.step("validate_guardrails")
        metadata = _compiled_metadata(context.base, context.metrics, context.dimensions, context.joins)
        metadata["trace"] = trace.snapshot()
        return CompiledQuery(sql=sql, parameters=parameters, metadata=metadata)

    async def _prepare_metric_plan(
        self,
        connection_id: int,
        spec: SemanticQuerySpec,
        metric: SemanticMetricModel,
        definition: MetricDefinition,
        dialect: str,
        trace: CompileTraceBuilder,
    ) -> MetricPlanCompileContext:
        plan = definition.metric.query_plan
        if plan is None:
            raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Metric plan is not canonical")
        metadata = await self._metadata.load_metric_plan_metadata(connection_id)
        self._metadata.resolve_plan_stages(plan, metadata, metric, definition)
        dimensions = await self._metadata.load_dimensions(connection_id, [item.column_id for item in spec.dimensions])
        apply_time_grains(dimensions, spec.dimensions)
        runtime_filters = await self._metadata.load_runtime_filters(connection_id, spec.filters)
        physical = next(stage for stage in plan.stages if stage.base_entity)
        trace.record(
            base_entity={"table_name": physical.base_entity, "table_id": metadata.tables[physical.base_entity].id},
            join_path=[
                hop
                for (base_name, _), joins in metadata.join_paths.items()
                for hop in trace_join_path(base_name, joins)
            ],
        )
        trace.step("validate_references")
        trace.step("resolve_joins")
        self._metadata.apply_plan_filters(plan, definition, runtime_filters, metadata)
        trace.record(
            dimensions=[{"column_id": item["column_id"], "time_grain": item.get("time_grain")} for item in dimensions],
            filters=trace_filters([definition], runtime_filters),
        )
        return MetricPlanCompileContext(
            plan=plan,
            metric=metric,
            dialect=dialect,
            tables=metadata.tables,
            columns=metadata.columns,
            join_paths=metadata.join_paths,
            dimensions=dimensions,
            dimension_grains={item.column_id: item.time_grain for item in spec.dimensions if item.time_grain},
            limit=spec.limit,
            order_by=spec.order_by,
        )

    def _render_metric_plan(self, context: MetricPlanCompileContext, trace: CompileTraceBuilder) -> CompiledQuery:
        parameters: dict[str, Any] = {}
        sql = compile_plan_sql(
            context.plan,
            context.metric.id,
            context.dialect,
            context.tables,
            context.columns,
            context.join_paths,
            context.dimensions,
            context.dimension_grains,
            [],
            context.limit,
            parameters,
            order_by=context.order_by,
        )
        trace.step("render_sql")
        validate_read_only(sql, context.dialect)
        trace.step("validate_guardrails")
        metadata = {
            "metric_plan": True,
            "metrics": {f"metric_{context.metric.id}": context.metric.name},
            "dimensions": {f"dimension_{item['column_id']}": item["business_name"] for item in context.dimensions},
            "relationship_ids": [item["relationship_id"] for joins in context.join_paths.values() for item in joins],
        }
        metadata["trace"] = trace.snapshot()
        return CompiledQuery(sql=sql, parameters=parameters, metadata=metadata)


def _compiled_metadata(
    base: SemanticTableModel,
    metrics: list[SemanticMetricModel],
    dimensions: list[dict[str, Any]],
    joins: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "base_entity": base.table_name,
        "metrics": {f"metric_{item.id}": item.name for item in metrics},
        "dimensions": {f"dimension_{item['column_id']}": item["business_name"] for item in dimensions},
        "relationship_ids": [item["relationship_id"] for item in joins],
    }
