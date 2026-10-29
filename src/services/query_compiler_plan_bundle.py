"""Render several approved metric plans on one shared output grain."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from src.models.metric_definition import MetricPlanStage, MetricQueryPlan
from src.services.query_compiler_plan import (
    _null_safe_equal,
    _output_expression,
    _plan_filter_error,
    _plan_order_clause,
    _quoted,
    _refs,
    _stage_sql,
)
from src.services.semantic_compile_error import SemanticCompileError

_RUNTIME_FILTERS_MSG = "Runtime filters must be resolved to stage-level filters by the caller before compilation"


def compile_plan_bundle_sql(
    metric_plans: list[tuple[int, MetricQueryPlan]],
    dialect: str,
    tables: dict[str, Any],
    columns: dict[str, dict[str, tuple[str, int, str]]],
    join_paths: dict[tuple[str, str], list[dict[str, str]]],
    runtime_dimensions: list[dict[str, Any]],
    dimension_grains: dict[int, str],
    runtime_filters: list[dict[str, Any]],
    limit: int,
    parameters: dict[str, Any],
    order_by: str | None = None,
    order_metric_id: int | None = None,
) -> str:
    """Compile metric plans into one aligned, bounded SELECT."""
    if runtime_filters:
        raise _plan_filter_error("unresolved_lineage", None, _RUNTIME_FILTERS_MSG)
    dimension_ids = [item["column_id"] for item in runtime_dimensions]
    prepared = [_prepare_bundle_plan(metric_id, plan, dimension_ids) for metric_id, plan in metric_plans]
    ctes = _bundle_stage_ctes(prepared, tables, columns, join_paths, dialect, parameters, dimension_grains)
    return _render_bundle_result(prepared, runtime_dimensions, dialect, limit, order_by, order_metric_id, ctes)


def _render_bundle_result(
    prepared: list[dict[str, Any]],
    dimensions: list[dict[str, Any]],
    dialect: str,
    limit: int,
    order_by: str | None,
    order_metric_id: int | None,
    ctes: list[str],
) -> str:
    terminals = [name for item in prepared for name in item["terminals"]]
    from_sql, dimension_sql = _bundle_from_and_dimensions(prepared, terminals, dimensions, dialect, ctes)
    metric_sql = [
        f"{_output_expression(item['expression'], item['terminals'], dialect)} AS "
        f"{_quoted('metric_' + str(item['metric_id']), dialect)}"
        for item in prepared
    ]
    result = f"SELECT {', '.join([*dimension_sql, *metric_sql])}\n{from_sql}"
    metric_id = order_metric_id or (prepared[0]["metric_id"] if len(prepared) == 1 else None)
    order_clause = _plan_order_clause(order_by, dimensions, metric_id, dialect)
    if not order_clause:
        return "WITH " + ",\n".join(ctes) + f"\n{result}\nLIMIT {limit}"
    result_name = _quoted("__metric_result", dialect)
    ctes.append(f"{result_name} AS ({result})")
    return "WITH " + ",\n".join(ctes) + f"\nSELECT * FROM {result_name}\n{order_clause}\nLIMIT {limit}"


def _prepare_bundle_plan(metric_id: int, plan: MetricQueryPlan, dimension_ids: list[int]) -> dict[str, Any]:
    copied = plan.model_copy(deep=True)
    mapping = {stage.name: f"m{metric_id}__{stage.name}" for stage in copied.stages}
    _namespace_plan(copied, mapping)
    stage_map = {stage.name: stage for stage in copied.stages}
    terminals = sorted({name for name, _ in _refs(copied.output_expression, stage_map)})
    signatures = [_terminal_grain(stage_map[name]) for name in terminals]
    if any(set(grain) != set(signatures[0]) for grain in signatures[1:]) or set(signatures[0]) != set(dimension_ids):
        if signatures[0] and not dimension_ids:
            raise SemanticCompileError("DIMENSION_REQUIRED", "Select a dimension declared by the metric plan")
        raise SemanticCompileError("INCOMPATIBLE_GRAIN", "Selected dimensions must match every metric plan grain")
    if len(signatures[0]) != len(set(signatures[0])):
        raise SemanticCompileError("INCOMPATIBLE_GRAIN", "Metric plan grouping keys must be unique")
    return {
        "metric_id": metric_id,
        "plan": copied,
        "stage_map": stage_map,
        "terminals": terminals,
        "expression": copied.output_expression,
    }


def _terminal_grain(stage: MetricPlanStage) -> tuple[int | None, ...]:
    return tuple(field.column_id for field in stage.group_by)


def _namespace_plan(plan: MetricQueryPlan, mapping: dict[str, str]) -> None:
    for stage in plan.stages:
        source = stage.source_stage
        if source:
            stage.source_stage = mapping[source]
            for item in [*stage.group_by, *stage.aggregates]:
                item.expression = _namespace_expression(item.expression, mapping)
            for item in stage.filters:
                item.field = _namespace_field(item.field, mapping)
            for aggregate in stage.aggregates:
                for item in aggregate.filters:
                    item.field = _namespace_field(item.field, mapping)
        stage.name = mapping[stage.name]
    plan.output_expression = _namespace_expression(plan.output_expression, mapping)


def _namespace_field(value: str, mapping: dict[str, str]) -> str:
    head, separator, tail = value.partition(".")
    return mapping.get(head, head) + (separator + tail if separator else "")


def _namespace_expression(value: str, mapping: dict[str, str]) -> str:
    parsed = sqlglot.parse_one(value)
    for column in parsed.find_all(exp.Column):
        if column.table in mapping:
            column.set("table", exp.to_identifier(mapping[column.table]))
    return parsed.sql()


def _bundle_stage_ctes(
    prepared: list[dict[str, Any]],
    tables: dict[str, Any],
    columns: dict[str, dict[str, tuple[str, int, str]]],
    join_paths: dict[tuple[str, str], list[dict[str, str]]],
    dialect: str,
    parameters: dict[str, Any],
    dimension_grains: dict[int, str],
) -> list[str]:
    return [
        _stage_sql(
            stage,
            item["stage_map"],
            tables,
            columns,
            join_paths,
            dialect,
            parameters,
            dimension_grains,
            f"metric_{item['metric_id']}_",
        )
        for item in prepared
        for stage in item["plan"].stages
    ]


def _bundle_from_and_dimensions(
    prepared: list[dict[str, Any]],
    terminals: list[str],
    dimensions: list[dict[str, Any]],
    dialect: str,
    ctes: list[str],
) -> tuple[str, list[str]]:
    if not dimensions:
        return "FROM " + " CROSS JOIN ".join(_quoted(name, dialect) for name in terminals), []
    keys = [f"__key_{item['column_id']}" for item in dimensions]
    ctes.append(_key_cte(prepared, dimensions, keys, dialect))
    from_sql = f"FROM {_quoted('__metric_keys', dialect)}"
    for item in prepared:
        for name in item["terminals"]:
            from_sql += _terminal_join(item["stage_map"][name], name, dimensions, keys, dialect)
    selected = [
        f"{_quoted('__metric_keys', dialect)}.{_quoted(key, dialect)} AS "
        f"{_quoted('dimension_' + str(item['column_id']), dialect)}"
        for item, key in zip(dimensions, keys, strict=True)
    ]
    return from_sql, selected


def _key_cte(prepared: list[dict[str, Any]], dimensions: list[dict[str, Any]], keys: list[str], dialect: str) -> str:
    selects = []
    for item in prepared:
        for name in item["terminals"]:
            fields = {field.column_id: field.name for field in item["stage_map"][name].group_by}
            values = ", ".join(
                f"{_quoted(fields[dimension['column_id']], dialect)} AS {_quoted(key, dialect)}"
                for dimension, key in zip(dimensions, keys, strict=True)
            )
            selects.append(f"SELECT {values} FROM {_quoted(name, dialect)}")  # noqa: S608
    return f"{_quoted('__metric_keys', dialect)} AS (" + " UNION ".join(selects) + ")"


def _terminal_join(
    stage: MetricPlanStage, name: str, dimensions: list[dict[str, Any]], keys: list[str], dialect: str
) -> str:
    fields = {field.column_id: field.name for field in stage.group_by}
    predicates = [
        _null_safe_equal(
            f"{_quoted('__metric_keys', dialect)}.{_quoted(key, dialect)}",
            f"{_quoted(name, dialect)}.{_quoted(fields[item['column_id']], dialect)}",
            dialect,
        )
        for item, key in zip(dimensions, keys, strict=True)
    ]
    return f" LEFT JOIN {_quoted(name, dialect)} ON " + " AND ".join(predicates)
