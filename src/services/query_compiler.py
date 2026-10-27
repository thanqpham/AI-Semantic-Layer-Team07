"""Compile approved metric definitions into parameterized read-only SQL."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from src.models.db import (
    CanonicalRelationshipModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.metric_definition import MetricDefinition, MetricExpressionNode, MetricPlanFilter
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.observability import trace_action
from src.services.metric_definition_resolver import expression_tree_for_columns
from src.services.metric_definitions import is_numeric_data_type
from src.services.query_compiler_plan import compile_plan_sql
from src.services.query_compiler_sql import (
    _assemble_sql,
    _coerce_literal,
    _column_info,
    _dimension_expressions,
    _fixed_predicates,
    _metric_expressions,
    _raw_qualified,
    _residual_filters,
    _shared_filters,
    validate_read_only,
)
from src.services.query_compiler_trace import CompileTraceBuilder
from src.services.semantic_compile_error import SemanticCompileError

__all__ = ["CompiledQuery", "SemanticQueryCompiler", "validate_read_only"]


@dataclass
class CompiledQuery:
    """Hold compiled SQL, bound values, and observable metadata."""

    sql: str
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def _query_spec(
    query: SemanticQuerySpec | list[int] | None,
    metric_ids: list[int] | None,
    dimension_ids: list[int] | None,
    filters: list[SemanticQueryFilter] | None,
    limit: int,
) -> SemanticQuerySpec:
    """Normalize legacy compiler arguments into the canonical input."""
    if isinstance(query, SemanticQuerySpec):
        return query
    selected_metrics = query if isinstance(query, list) else metric_ids
    dimensions = [DimensionSelection(column_id=item) for item in dimension_ids or []]
    return SemanticQuerySpec(
        metric_ids=selected_metrics or [],
        dimensions=dimensions,
        filters=filters or [],
        limit=min(limit, 1000),
    )


def _reject_duplicate_selections(spec: SemanticQuerySpec) -> None:
    metric_ids = spec.metric_ids
    dimension_ids = [item.column_id for item in spec.dimensions]
    if len(metric_ids) != len(set(metric_ids)) or len(dimension_ids) != len(set(dimension_ids)):
        raise SemanticCompileError("DUPLICATE_SELECTION", "Semantic selections must be unique")


def _attach_partial_trace(exc: SemanticCompileError, trace: CompileTraceBuilder) -> None:
    """Attach a safe partial trace when at least one compile phase completed."""
    if trace.completed_steps:
        exc.context.setdefault("partial_trace", trace.snapshot())


class SemanticQueryCompiler:
    """Compile approved definitions and selected dimensions through one interface."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def compile(
        self,
        connection_id: int,
        query: SemanticQuerySpec | list[int] | None = None,
        dimension_ids: list[int] | None = None,
        filters: list[SemanticQueryFilter] | None = None,
        limit: int = 100,
        *,
        metric_ids: list[int] | None = None,
    ) -> CompiledQuery:
        """Compile semantic selections without accepting SQL from the caller."""
        spec = _query_spec(query, metric_ids, dimension_ids, filters, limit)
        _reject_duplicate_selections(spec)
        trace = CompileTraceBuilder()
        try:
            return await trace_action(
                "query_compile",
                {"connection_id": connection_id, "metric_count": len(spec.metric_ids)},
                self._compile_spec(connection_id, spec, trace),
            )
        except SemanticCompileError as exc:
            _attach_partial_trace(exc, trace)
            raise

    async def _compile_spec(
        self, connection_id: int, spec: SemanticQuerySpec, trace: CompileTraceBuilder
    ) -> CompiledQuery:
        dialect = await self._load_dialect(connection_id)
        metrics = await self._load_metrics(connection_id, spec.metric_ids)
        definitions = _canonical_definitions(metrics)
        _record_loaded_trace(trace, metrics, definitions, spec.limit)
        if any(item.metric.query_plan is not None for item in definitions):
            if len(definitions) != 1 or definitions[0].metric.query_plan is None:
                raise SemanticCompileError(
                    "INCOMPATIBLE_QUERY_PLAN", "Multi-table plans must be queried one metric at a time"
                )
            return await self._compile_plan(connection_id, spec, metrics[0], definitions[0], trace)
        trace.record(plan_type="single_table")
        base_name = self._require_same_base(definitions)
        tables = await self._load_tables(connection_id)
        table_by_id = {table.id: table for table in tables}
        table_by_name = {table.table_name: table for table in tables}
        base = table_by_name.get(base_name)
        if base is None:
            raise ValueError(f"Unknown base entity: {base_name}")
        dimensions = await self._load_dimensions(connection_id, [item.column_id for item in spec.dimensions])
        base_columns = await self._load_base_columns(base.id)
        _validate_definition_asts(definitions, base_columns)
        _apply_time_grains(dimensions, spec.dimensions)
        trace.record(base_entity={"table_name": base.table_name, "table_id": base.id})
        trace.step("validate_references")
        runtime_filters = await self._load_runtime_filters(connection_id, spec.filters)
        joins = await self._resolve_joins(connection_id, base, dimensions + runtime_filters, table_by_id, trace)
        return self._build_query(
            dialect,
            metrics,
            definitions,
            base,
            base_columns,
            dimensions,
            joins,
            runtime_filters,
            spec.limit,
            spec.order_by,
            trace,
        )

    async def _compile_plan(
        self,
        connection_id: int,
        spec: SemanticQuerySpec,
        metric: SemanticMetricModel,
        definition: MetricDefinition,
        trace: CompileTraceBuilder,
    ) -> CompiledQuery:
        plan = definition.metric.query_plan
        trace.record(plan_type="metric_plan")
        dialect = await self._load_dialect(connection_id)
        tables_list = await self._load_tables(connection_id)
        tables = {table.table_name: table for table in tables_list}
        tables_folded = {table.table_name.casefold(): table for table in tables_list}
        result = await self._db.execute(
            select(SemanticColumnModel).where(SemanticColumnModel.table_id.in_([t.id for t in tables_list]))
        )
        all_columns = list(result.scalars().all())
        columns: dict[str, dict[str, tuple[str, int, str]]] = {}
        by_id: dict[int, tuple[str, str, int, str]] = {}
        for column in all_columns:
            table = next(item for item in tables_list if item.id == column.table_id)
            columns.setdefault(table.table_name, {})[column.column_name] = (
                column.column_name,
                column.id,
                column.data_type or "",
            )
            by_id[column.id] = (table.table_name, column.column_name, column.id, column.data_type or "")
        relationships_result = await self._db.execute(
            select(CanonicalRelationshipModel).where(CanonicalRelationshipModel.connection_id == connection_id)
        )
        relationships = [
            item for item in relationships_result.scalars().all() if item.validation_status in {"valid", None}
        ]
        relationship_columns = await self._relationship_columns(relationships)
        join_paths: dict[tuple[str, str], list[dict[str, str]]] = {}
        stage_tables: dict[str, set[str]] = {}
        for stage in plan.stages:
            if stage.source_stage:
                stage_tables[stage.name] = set(stage_tables[stage.source_stage])
                parent = next(item for item in plan.stages if item.name == stage.source_stage)
                for field in stage.group_by:
                    if field.column_id is None:
                        field_name = field.expression.split(".", 1)[-1]
                        field.column_id = next(
                            (item.column_id for item in parent.group_by if item.name == field_name), None
                        )
                continue
            base = tables_folded.get(stage.base_entity.casefold())
            if base is None:
                raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric plan references an unknown source table")
            stage.base_entity = base.table_name
            stage_tables[stage.name] = {base.table_name}
            resolved_joins = []
            for requested in list(stage.joins):
                target = tables_folded.get(requested.casefold())
                if target is None:
                    raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric plan references an unknown joined table")
                if target.id == base.id:
                    raise SemanticCompileError("UNSAFE_JOIN", "Metric plan cannot join its source table to itself")
                path = _safe_join_path(
                    relationships, base.id, target.id, {t.id: t for t in tables_list}, relationship_columns
                )
                path_joins = []
                for rel in path:
                    rel_target = tables[next(t.table_name for t in tables_list if t.id == rel.to_entity_id)]
                    path_joins.append(
                        {
                            "relationship_id": rel.id,
                            "table_name": rel_target.table_name,
                            "physical_schema": rel_target.physical_schema,
                            "condition": _relationship_condition(rel, relationship_columns),
                        }
                    )
                    stage_tables[stage.name].add(rel_target.table_name)
                join_paths[(base.table_name, target.table_name)] = path_joins
                resolved_joins.append(target.table_name)
            stage.joins = list(dict.fromkeys(resolved_joins))
            for field in stage.group_by:
                if field.column_id is not None:
                    resolved = by_id.get(field.column_id)
                else:
                    parsed = sqlglot.parse_one(field.expression)
                    if not isinstance(parsed, exp.Column):
                        raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric plan grouping key must be a column")
                    source_name = parsed.table or stage.base_entity
                    resolved = next(
                        (
                            (source_name, name, column_id, data_type)
                            for name, (name, column_id, data_type) in columns.get(source_name, {}).items()
                            if name.casefold() == parsed.name.casefold()
                        ),
                        None,
                    )
                if not resolved or resolved[0] not in stage_tables[stage.name]:
                    raise SemanticCompileError(
                        "UNKNOWN_REFERENCE", "Metric plan grouping key does not match its source tables"
                    )
                field.column_id = resolved[2]
                field.expression = f"{resolved[0]}.{resolved[1]}"
            for aggregate in stage.aggregates:
                for filter_item in aggregate.filters:
                    if filter_item.column_id is not None:
                        resolved = by_id.get(filter_item.column_id)
                        if not resolved or resolved[0] not in stage_tables[stage.name]:
                            raise SemanticCompileError(
                                "UNKNOWN_REFERENCE", "Metric plan filter does not match its source tables"
                            )
                        filter_item.field = f"{resolved[0]}.{resolved[1]}"
            for filter_item in stage.filters:
                if filter_item.column_id is not None:
                    resolved = by_id.get(filter_item.column_id)
                    if not resolved or resolved[0] not in stage_tables[stage.name]:
                        raise SemanticCompileError(
                            "UNKNOWN_REFERENCE", "Metric plan filter does not match its source tables"
                        )
                    filter_item.field = f"{resolved[0]}.{resolved[1]}"
        dimensions = await self._load_dimensions(connection_id, [item.column_id for item in spec.dimensions])
        _apply_time_grains(dimensions, spec.dimensions)
        runtime_filters = await self._load_runtime_filters(connection_id, spec.filters)
        physical_stages = [stage for stage in plan.stages if stage.base_entity]
        trace.record(
            base_entity={
                "table_name": physical_stages[0].base_entity,
                "table_id": tables[physical_stages[0].base_entity].id,
            },
            join_path=_plan_trace_join_path(join_paths),
        )
        trace.step("validate_references")
        trace.step("resolve_joins")
        scoped_filters = [
            {"column_id": item.column_id, "operator": item.operator, "value": item.value}
            for item in definition.metric.filters
        ] + runtime_filters
        for item in scoped_filters:
            column_id = item["column_id"]
            resolved = by_id.get(column_id)
            if resolved is None or any(resolved[0] not in stage_tables[stage.name] for stage in physical_stages):
                raise SemanticCompileError(
                    "UNSUPPORTED_PLAN_FILTER",
                    "Runtime filters must reference the same approved table in every source stage",
                )
            for stage in physical_stages:
                value = item["value"]
                value = (
                    [_coerce_literal(member, resolved[3]) for member in value]
                    if item["operator"] in {"in", "not_in"}
                    else _coerce_literal(value, resolved[3])
                )
                stage.filters.append(
                    MetricPlanFilter(
                        field=f"{resolved[0]}.{resolved[1]}",
                        operator=item["operator"],
                        value=value,
                        column_id=column_id,
                    )
                )
        trace.record(
            dimensions=[{"column_id": item["column_id"], "time_grain": item.get("time_grain")} for item in dimensions],
            filters=_trace_filters([definition], runtime_filters),
        )
        parameters: dict[str, Any] = {}
        sql = compile_plan_sql(
            plan,
            metric.id,
            dialect,
            tables,
            columns,
            join_paths,
            dimensions,
            {item.column_id: item.time_grain for item in spec.dimensions if item.time_grain},
            [],
            spec.limit,
            parameters,
            order_by=spec.order_by,
        )
        trace.step("render_sql")
        validate_read_only(sql, dialect)
        trace.step("validate_guardrails")
        metadata = {
            "metric_plan": True,
            "metrics": {f"metric_{metric.id}": metric.name},
            "dimensions": {f"dimension_{item['column_id']}": item["business_name"] for item in dimensions},
            "relationship_ids": [item["relationship_id"] for joins in join_paths.values() for item in joins],
        }
        metadata["trace"] = trace.snapshot()
        return CompiledQuery(sql=sql, parameters=parameters, metadata=metadata)

    async def _load_dialect(self, connection_id: int) -> str:
        record = await self._db.get(SemanticDatabaseModel, connection_id)
        if record is None:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Semantic database not found")
        return {"postgresql": "postgres", "mysql": "mysql", "sqlite": "sqlite"}.get(record.db_type, record.db_type)

    async def _load_metrics(self, db_id: int, ids: list[int]) -> list[SemanticMetricModel]:
        result = await self._db.execute(
            select(SemanticMetricModel).where(
                SemanticMetricModel.db_id == db_id,
                SemanticMetricModel.id.in_(ids),
                SemanticMetricModel.is_deleted.is_(False),
            )
        )
        found = {item.id: item for item in result.scalars().all()}
        if missing := set(ids) - found.keys():
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Metrics not found", {"metric_ids": sorted(missing)})
        metrics = [found[item_id] for item_id in ids]
        for metric in metrics:
            if metric.status != "approved" or metric.definition is None:
                code = "METRIC_NEEDS_REVIEW" if metric.status == "needs_review" else "METRIC_NOT_APPROVED"
                raise SemanticCompileError(code, f"Metric '{metric.name}' is not approved", {"metric_id": metric.id})
        return metrics

    @staticmethod
    def _require_same_base(definitions: list[MetricDefinition]) -> str:
        bases = {item.metric.base_entity for item in definitions}
        if len(bases) != 1:
            raise SemanticCompileError("INCOMPATIBLE_BASE_ENTITY", "All selected metrics must use the same base entity")
        return bases.pop()

    async def _load_tables(self, db_id: int) -> list[SemanticTableModel]:
        result = await self._db.execute(select(SemanticTableModel).where(SemanticTableModel.db_id == db_id))
        return list(result.scalars().all())

    async def _load_base_columns(self, table_id: int) -> dict[int, tuple[str, str]]:
        result = await self._db.execute(select(SemanticColumnModel).where(SemanticColumnModel.table_id == table_id))
        return {c.id: (c.column_name, c.data_type or "") for c in result.scalars().all()}

    async def _load_dimensions(self, db_id: int, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        stmt = (
            select(SemanticColumnModel, SemanticTableModel)
            .join(SemanticTableModel, SemanticColumnModel.table_id == SemanticTableModel.id)
            .where(SemanticTableModel.db_id == db_id, SemanticColumnModel.id.in_(ids))
        )
        rows = list((await self._db.execute(stmt)).all())
        by_id = {column.id: _column_info(column, table) for column, table in rows}
        if missing := set(ids) - by_id.keys():
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Columns not found", {"column_ids": sorted(missing)})
        return [by_id[item_id] for item_id in ids]

    async def _load_runtime_filters(self, db_id: int, filters: list[SemanticQueryFilter]) -> list[dict[str, Any]]:
        if not filters:
            return []
        columns = await self._load_dimensions(db_id, [item.column_id for item in filters])
        return [
            {**column, "operator": item.operator, "value": item.value}
            for column, item in zip(columns, filters, strict=True)
        ]

    async def _resolve_joins(
        self,
        db_id: int,
        base: SemanticTableModel,
        dimensions: list[dict[str, Any]],
        tables: dict[int, SemanticTableModel],
        trace: CompileTraceBuilder,
    ) -> list[dict[str, Any]]:
        result = await self._db.execute(
            select(CanonicalRelationshipModel).where(CanonicalRelationshipModel.connection_id == db_id)
        )
        relationships = [item for item in result.scalars().all() if item.validation_status in {"valid", None}]
        column_names = await self._relationship_columns(relationships)
        joins: list[dict[str, str]] = []
        joined = {base.id}
        for table_id in {item["table_id"] for item in dimensions} - joined:
            for relationship in _safe_join_path(relationships, base.id, table_id, tables, column_names):
                target_id = relationship.to_entity_id
                if target_id not in joined:
                    joins.append(
                        {
                            "relationship_id": relationship.id,
                            "table_name": tables[target_id].table_name,
                            "physical_schema": tables[target_id].physical_schema,
                            "condition": _relationship_condition(relationship, column_names),
                        }
                    )
                    joined.add(target_id)
        _record_join_trace(trace, base.table_name, joins)
        return joins

    async def _relationship_columns(
        self,
        relationships: list[CanonicalRelationshipModel],
    ) -> dict[int, tuple[str, str]]:
        ids = {
            value
            for relationship in relationships
            for pair in relationship.column_pairs or []
            for value in (pair["from_column_id"], pair["to_column_id"])
        }
        if not ids:
            return {}
        stmt = (
            select(SemanticColumnModel, SemanticTableModel)
            .join(SemanticTableModel, SemanticColumnModel.table_id == SemanticTableModel.id)
            .where(SemanticColumnModel.id.in_(ids))
        )
        return {
            column.id: (table.table_name, column.column_name) for column, table in (await self._db.execute(stmt)).all()
        }

    def _build_query(
        self,
        dialect: str,
        metrics: list[SemanticMetricModel],
        definitions: list[MetricDefinition],
        base: SemanticTableModel,
        base_columns: dict[int, tuple[str, str]],
        dimensions: list[dict[str, Any]],
        joins: list[dict[str, Any]],
        runtime_filters: list[dict[str, Any]],
        limit: int,
        order_by: str | None,
        trace: CompileTraceBuilder,
    ) -> CompiledQuery:
        _record_render_trace(trace, dimensions, definitions, runtime_filters)
        parameters: dict[str, Any] = {}
        names = {cid: name for cid, (name, _) in base_columns.items()}
        types = {cid: dt for cid, (_, dt) in base_columns.items()}
        dimensions_sql, group_sql = _dimension_expressions(dimensions, dialect)
        shared = _shared_filters(definitions)
        residuals = [_residual_filters(d, shared) for d in definitions]
        fixed = _fixed_predicates(shared, names, types, base.table_name, dialect, parameters)
        metrics_sql = _metric_expressions(metrics, definitions, base, names, types, dialect, parameters, residuals)
        sql = _assemble_sql(
            dimensions_sql + metrics_sql,
            base,
            joins,
            runtime_filters,
            group_sql,
            dialect,
            parameters,
            limit,
            fixed,
            order_by,
        )
        trace.step("render_sql")
        validate_read_only(sql)
        trace.step("validate_guardrails")
        metadata = _compiled_metadata(base, metrics, dimensions, joins)
        metadata["trace"] = trace.snapshot()
        return CompiledQuery(sql=sql, parameters=parameters, metadata=metadata)


def _canonical_definitions(metrics: list[SemanticMetricModel]) -> list[MetricDefinition]:
    definitions = [MetricDefinition.model_validate(item.definition) for item in metrics]
    invalid = (
        item.schema_version not in {2, 3}
        or item.diagnostics
        or (item.schema_version == 2 and not item.metric.grain.column_ids)
        or (item.schema_version == 3 and item.metric.query_plan is None)
        for item in definitions
    )
    if any(invalid):
        raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Metric definition is not canonical v2")
    return definitions


def _validate_definition_asts(
    definitions: list[MetricDefinition],
    columns: dict[int, tuple[str, str]],
) -> None:
    """Ensure persisted expression trees still match their readable formulas."""
    column_ids = {name: column_id for column_id, (name, _) in columns.items()}
    for definition in definitions:
        formula = definition.metric.formula
        _validate_expression_ast(formula.expression, formula.expression_ast, column_ids)
        _validate_numeric_aggregate(formula.function, formula.expression_ast, columns)
        if formula.ratio is None:
            continue
        for aggregate in (formula.ratio.numerator, formula.ratio.denominator):
            _validate_expression_ast(aggregate.expression, aggregate.expression_ast, column_ids)
            _validate_numeric_aggregate(aggregate.function, aggregate.expression_ast, columns)


def _validate_expression_ast(
    expression: str,
    expression_ast: MetricExpressionNode | None,
    column_ids: dict[str, int],
) -> None:
    if expression_ast is None:
        raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Metric expression is not resolved")
    try:
        expected = expression_tree_for_columns(expression, column_ids)
    except (KeyError, ValueError) as exc:
        raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Metric expression references an unknown column") from exc
    if expression_ast != expected:
        raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Metric expression does not match its resolved AST")


def _validate_numeric_aggregate(
    function: str,
    expression: MetricExpressionNode | None,
    columns: dict[int, tuple[str, str]],
) -> None:
    if function not in {"SUM", "AVG"} or expression is None:
        return
    if expression.kind == "timestamp_diff_hours":
        return
    pending = [expression]
    invalid: set[str] = set()
    while pending:
        node = pending.pop()
        pending.extend(node.children)
        if node.kind == "column" and node.column_id in columns and not is_numeric_data_type(columns[node.column_id][1]):
            invalid.add(columns[node.column_id][0])
    if invalid:
        raise SemanticCompileError(
            "METRIC_NEEDS_REVIEW",
            f"{function} requires numeric columns",
            {"columns": sorted(invalid)},
        )


def _apply_time_grains(dimensions: list[dict[str, Any]], selections: list[DimensionSelection]) -> None:
    for dimension, selection in zip(dimensions, selections, strict=True):
        dimension["time_grain"] = selection.time_grain
        if selection.time_grain and not dimension["is_time_dimension"]:
            raise SemanticCompileError(
                "INVALID_TIME_GRAIN",
                f"Column {selection.column_id} is not a time dimension",
                {"column_id": selection.column_id},
            )


def _safe_join_path(
    relationships: list[CanonicalRelationshipModel],
    base_id: int,
    table_id: int,
    tables: dict[int, SemanticTableModel] | None = None,
    column_names: dict[int, tuple[str, str]] | None = None,
) -> list[CanonicalRelationshipModel]:
    paths = _many_to_one_paths(relationships, base_id, table_id)
    if len(paths) > 1:
        if tables and column_names and table_id in tables:
            target_table = tables[table_id].table_name.lower().rstrip("s")

            def _path_score(p: list[CanonicalRelationshipModel]) -> tuple[int, int, int]:
                hop_len = len(p)
                match_name = 0
                if hop_len == 1 and p[0].column_pairs:
                    from_col_id = p[0].column_pairs[0].get("from_column_id")
                    if from_col_id in column_names:
                        col_name = column_names[from_col_id][1].lower()
                        if col_name in {f"{target_table}_id", f"{target_table}id", target_table}:
                            match_name = -1
                return (hop_len, match_name, p[0].id if p else 0)

            ranked = sorted(paths, key=_path_score)
            return ranked[0]
        raise SemanticCompileError("AMBIGUOUS_JOIN_PATH", "Multiple safe join paths exist", {"table_id": table_id})
    if not paths:
        _raise_unreachable(relationships, base_id, table_id)
    return paths[0]


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


def _trace_metric(metric: SemanticMetricModel, definition: MetricDefinition) -> dict[str, Any]:
    """Describe one approved metric for the trace without exposing filter values."""
    return {
        "id": metric.id,
        "name": metric.name,
        "version": metric.version,
        "grain_column_ids": list(definition.metric.grain.column_ids),
    }


def _trace_join_path(base_name: str, joins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe resolved joins in render order; from_table is the query base."""
    return [
        {"relationship_id": join["relationship_id"], "from_table": base_name, "to_table": join["table_name"]}
        for join in joins
    ]


def _trace_filters(
    definitions: list[MetricDefinition],
    runtime_filters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Describe filter references only; values are never included."""
    entries: list[dict[str, Any]] = []
    for definition in definitions:
        for item in definition.metric.filters:
            if item.column_id is not None:
                entries.append({"column_id": item.column_id, "operator": item.operator, "scope": "metric"})
    for item in runtime_filters:
        entries.append({"column_id": item["column_id"], "operator": item["operator"], "scope": "runtime"})
    unique: dict[str, dict[str, Any]] = {}
    for entry in entries:
        unique.setdefault(json.dumps(entry, sort_keys=True), entry)
    return list(unique.values())


def _record_loaded_trace(
    trace: CompileTraceBuilder,
    metrics: list[SemanticMetricModel],
    definitions: list[MetricDefinition],
    limit: int,
) -> None:
    """Record loaded metric references and the effective limit for the trace."""
    trace.record(
        metrics=[_trace_metric(metric, definition) for metric, definition in zip(metrics, definitions, strict=True)],
        effective_limit=limit,
    )
    trace.step("load_metadata")


def _record_join_trace(trace: CompileTraceBuilder, base_name: str, joins: list[dict[str, Any]]) -> None:
    """Record the resolved join path and mark the resolve_joins phase complete."""
    trace.record(join_path=_trace_join_path(base_name, joins))
    trace.step("resolve_joins")


def _record_render_trace(
    trace: CompileTraceBuilder,
    dimensions: list[dict[str, Any]],
    definitions: list[MetricDefinition],
    runtime_filters: list[dict[str, Any]],
) -> None:
    """Record resolved dimension and filter references before SQL rendering."""
    trace.record(
        dimensions=[{"column_id": item["column_id"], "time_grain": item["time_grain"]} for item in dimensions],
        filters=_trace_filters(definitions, runtime_filters),
    )


def _plan_trace_join_path(join_paths: dict[tuple[str, str], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Flatten per-stage join paths in stage order for the trace."""
    return [
        {"relationship_id": hop["relationship_id"], "from_table": base_name, "to_table": hop["table_name"]}
        for (base_name, _target), hops in join_paths.items()
        for hop in hops
    ]


def _many_to_one_paths(
    relationships: list[CanonicalRelationshipModel], start: int, target: int
) -> list[list[CanonicalRelationshipModel]]:
    graph: dict[int, list[CanonicalRelationshipModel]] = {}
    for rel in relationships:
        if rel.relationship_type in {"many_to_one", "many-to-one"}:
            graph.setdefault(rel.from_entity_id, []).append(rel)
    queue: deque[tuple[int, list[CanonicalRelationshipModel], set[int]]] = deque([(start, [], {start})])
    matches: list[list[CanonicalRelationshipModel]] = []
    shortest: int | None = None
    while queue:
        current, path, visited = queue.popleft()
        if current == target:
            shortest = len(path) if shortest is None else shortest
            if len(path) == shortest:
                matches.append(path)
            continue
        if shortest is not None and len(path) >= shortest:
            continue
        for relationship in graph.get(current, []):
            if relationship.to_entity_id not in visited:
                queue.append(
                    (
                        relationship.to_entity_id,
                        [*path, relationship],
                        {*visited, relationship.to_entity_id},
                    )
                )
    return matches


def _raise_unreachable(
    relationships: list[CanonicalRelationshipModel],
    base_id: int,
    target_id: int,
) -> None:
    reverse_paths = _many_to_one_paths(relationships, target_id, base_id)
    if reverse_paths:
        raise SemanticCompileError("UNSAFE_FANOUT", "Dimension requires a one-to-many join", {"table_id": target_id})
    raise SemanticCompileError(
        "UNREACHABLE_DIMENSION", "Dimension is not reachable through a safe path", {"table_id": target_id}
    )


def _relationship_condition(
    relationship: CanonicalRelationshipModel,
    columns: dict[int, tuple[str, str]],
) -> str:
    if relationship.column_pairs:
        predicates = [
            f"{_raw_qualified(columns[pair['from_column_id']])} = {_raw_qualified(columns[pair['to_column_id']])}"
            for pair in relationship.column_pairs
        ]
        return " AND ".join(predicates)
    raise SemanticCompileError(
        "RELATIONSHIP_NEEDS_REVIEW",
        "Relationship does not contain canonical column pairs",
        {"relationship_id": relationship.id},
    )
