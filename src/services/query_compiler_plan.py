"""Compile bounded, metadata-backed multi-table metric plans."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from src.models.metric_definition import MetricPlanStage
from src.services.query_compiler_sql import _normalize_value, _quoted, _table_name, _validated_join_condition
from src.services.semantic_compile_error import SemanticCompileError


def compile_plan_sql(
    plan: Any,
    metric_id: int,
    dialect: str,
    tables: dict[str, Any],
    columns: dict[str, dict[str, tuple[str, int, str]]],
    join_paths: dict[tuple[str, str], list[dict[str, str]]],
    runtime_dimensions: list[dict[str, Any]],
    dimension_grains: dict[int, str],
    runtime_filters: list[dict[str, Any]],
    limit: int,
    parameters: dict[str, Any],
) -> str:
    """Render stage CTEs and a result aligned on their declared grouping names."""
    stage_map = {stage.name: stage for stage in plan.stages}
    output_refs = _refs(plan.output_expression, stage_map)
    terminals = sorted({stage for stage, _ in output_refs})
    if not terminals:
        raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Output expression must reference a plan stage")
    group_names = [field.name for field in stage_map[terminals[0]].group_by]
    if any([field.name for field in stage_map[name].group_by] != group_names for name in terminals):
        raise SemanticCompileError("INCOMPATIBLE_GRAIN", "Metric plan result stages must share the same grouping grain")
    selected_group_names = set()
    for dimension in runtime_dimensions:
        match = [
            field
            for field in stage_map[terminals[0]].group_by
            if field.column_id == dimension["column_id"]
        ]
        if not match or any(
            not any(field.name == match[0].name and field.column_id == dimension["column_id"] for field in stage_map[name].group_by)
            for name in terminals
        ):
            raise SemanticCompileError("INCOMPATIBLE_GRAIN", "Selected dimension is not present in every result stage")
        selected_group_names.add(match[0].name)
    if group_names and not runtime_dimensions:
        # Grouped plans need an explicit output dimension to avoid returning hidden grain rows.
        raise SemanticCompileError("DIMENSION_REQUIRED", "Select a dimension declared by the metric plan")
    if set(group_names) != selected_group_names:
        raise SemanticCompileError("INCOMPATIBLE_GRAIN", "Selected dimensions must match the metric plan's complete result grain")
    if runtime_filters:
        raise SemanticCompileError(
            "UNSUPPORTED_PLAN_FILTER",
            "Runtime filters are not yet mapped to every source stage; define the filter on the metric plan.",
        )

    ctes: list[str] = []
    for stage in plan.stages:
        ctes.append(_stage_sql(stage, stage_map, tables, columns, join_paths, dialect, parameters, dimension_grains))
    if group_names:
        key_columns = ", ".join(_quoted(name, dialect) for name in group_names)
        # Stage names and output identifiers are validated models and quoted per dialect.
        key_parts = [f"SELECT {key_columns} FROM {_quoted(name, dialect)}" for name in terminals]  # noqa: S608
        ctes.append(f"{_quoted('__metric_keys', dialect)} AS (" + " UNION ".join(key_parts) + ")")
        from_sql = f"FROM {_quoted('__metric_keys', dialect)}"
        for name in terminals:
            condition = " AND ".join(
                _null_safe_equal(
                    f"{_quoted('__metric_keys', dialect)}.{_quoted(key, dialect)}",
                    f"{_quoted(name, dialect)}.{_quoted(key, dialect)}",
                    dialect,
                )
                for key in group_names
            )
            from_sql += f" LEFT JOIN {_quoted(name, dialect)} ON {condition}"
        selected_dimensions = []
        for dimension in runtime_dimensions:
            field = next(item for item in stage_map[terminals[0]].group_by if item.column_id == dimension["column_id"])
            selected_dimensions.append(
                f"{_quoted('__metric_keys', dialect)}.{_quoted(field.name, dialect)} AS "
                f"{_quoted('dimension_' + str(dimension['column_id']), dialect)}"
            )
    else:
        from_sql = "FROM " + " CROSS JOIN ".join(_quoted(name, dialect) for name in terminals)
        selected_dimensions = []
    expression = _output_expression(plan.output_expression, terminals, dialect)
    metric = f"{expression} AS {_quoted('metric_' + str(metric_id), dialect)}"
    selections = ", ".join([*selected_dimensions, metric])
    return "WITH " + ",\n".join(ctes) + f"\nSELECT {selections}\n{from_sql}\nLIMIT {limit}"


def _stage_sql(
    stage: MetricPlanStage,
    stage_map: dict[str, MetricPlanStage],
    tables: dict[str, Any],
    columns: dict[str, dict[str, tuple[str, int, str]]],
    join_paths: dict[tuple[str, str], list[dict[str, str]]],
    dialect: str,
    parameters: dict[str, Any],
    dimension_grains: dict[int, str],
) -> str:
    if stage.source_stage:
        source = stage_map[stage.source_stage]
        from_sql = _quoted(source.name, dialect)
        available = {field.name for field in source.group_by} | {item.name for item in source.aggregates}
        source_table = None
    else:
        source_table = stage.base_entity
        if source_table not in tables:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric plan references an unknown source table")
        if any(target not in tables for target in stage.joins):
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric plan references an unknown joined table")
        joins: list[dict[str, str]] = []
        joined = {stage.base_entity}
        for target in stage.joins:
            for join in join_paths.get((stage.base_entity, target), []):
                if join["table_name"] not in joined:
                    joins.append(join)
                    joined.add(join["table_name"])
        if not set(stage.joins).issubset(joined):
            raise SemanticCompileError("UNSAFE_JOIN", "Metric plan join path is incomplete or fanout-prone")
        from_sql = _table_name(tables[stage.base_entity].physical_schema, stage.base_entity, dialect)
        for join in joins:
            condition = _validated_join_condition(join["condition"], dialect)
            target = _table_name(join["physical_schema"], join["table_name"], dialect)
            from_sql += f" JOIN {target} ON {condition}"
        available = set()

    group_expressions = []
    for item in stage.group_by:
        expression = _plan_expression(item.expression, stage, source_table, columns, available, dialect)
        if item.column_id in dimension_grains:
            expression = _time_bucket(expression, dimension_grains[item.column_id], dialect)
        group_expressions.append(expression)
    selected = [
        f"{expression} AS {_quoted(item.name, dialect)}"
        for item, expression in zip(stage.group_by, group_expressions, strict=True)
    ]
    where = [
        _plan_filter(item, stage, source_table, columns, available, dialect, parameters, "plan")
        for item in stage.filters
    ]
    for aggregate in stage.aggregates:
        argument = "1" if aggregate.expression == "*" else _plan_expression(
            aggregate.expression, stage, source_table, columns, available, dialect
        )
        predicates = [
            _plan_filter(item, stage, source_table, columns, available, dialect, parameters, aggregate.name)
            for item in aggregate.filters
        ]
        if predicates:
            argument = f"CASE WHEN {' AND '.join(predicates)} THEN {argument} END"
        expression = f"COUNT(DISTINCT {argument})" if aggregate.function == "COUNT_DISTINCT" else f"{aggregate.function}({argument})"
        selected.append(f"{expression} AS {_quoted(aggregate.name, dialect)}")
    if not selected:
        raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Metric plan stage has no outputs")
    group = group_expressions
    sql = f"SELECT {', '.join(selected)} FROM {from_sql}"  # noqa: S608
    if where:
        sql += " WHERE " + " AND ".join(where)
    if group:
        sql += " GROUP BY " + ", ".join(group)
    return f"{_quoted(stage.name, dialect)} AS ({sql})"


def _plan_expression(
    value: str,
    stage: MetricPlanStage,
    source_table: str | None,
    columns: dict[str, dict[str, tuple[str, int, str]]],
    available: set[str],
    dialect: str,
) -> str:
    parsed = sqlglot.parse_one(value)
    for column in list(parsed.find_all(exp.Column)):
        table, name = column.table, column.name
        if source_table is None:
            if (table and table.casefold() != (stage.source_stage or "").casefold()) or name not in available:
                raise SemanticCompileError("UNKNOWN_REFERENCE", "Stage expression references an unknown previous output")
            replacement = exp.column(name, quoted=True)
            if column is parsed:
                parsed = replacement
            else:
                column.replace(replacement)
            continue
        table = table or source_table
        record = columns.get(table, {}).get(name)
        if table not in {source_table, *stage.joins} or record is None:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Stage expression references an unknown table or column")
        replacement = exp.column(record[0], table=table, quoted=True)
        if column is parsed:
            parsed = replacement
        else:
            column.replace(replacement)
    for division in parsed.find_all(exp.Div):
        division.set("expression", exp.func("NULLIF", division.expression.copy(), exp.Literal.number(0)))
        division.set("this", _cast_dividend(division.this, dialect))
    return parsed.sql(dialect=dialect)


def _plan_filter(
    item: Any,
    stage: MetricPlanStage,
    source_table: str | None,
    columns: dict[str, dict[str, tuple[str, int, str]]],
    available: set[str],
    dialect: str,
    parameters: dict[str, Any],
    prefix: str,
) -> str:
    field = item.field
    if source_table is None:
        stage_name, name = field.split(".", 1) if "." in field else (None, field)
        if (stage_name and stage_name.casefold() != (stage.source_stage or "").casefold()) or name not in available:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Stage filter references an unknown previous output")
        column = f"{_quoted(name, dialect)}"
    else:
        table, name = field.split(".", 1) if "." in field else (source_table, field)
        record = columns.get(table, {}).get(name)
        if table not in {source_table, *stage.joins} or record is None:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Stage filter references an unknown table or column")
        column = f"{_quoted(table, dialect)}.{_quoted(record[0], dialect)}"
    if item.operator == "is_null":
        return column + " IS NULL"
    if item.operator == "is_not_null":
        return column + " IS NOT NULL"
    if item.operator in {"in", "not_in"}:
        names = []
        for value in item.value:
            key = f"{prefix}_{len(parameters)}"
            parameters[key] = _normalize_value(value)
            names.append(":" + key)
        return f"{column} {'NOT IN' if item.operator == 'not_in' else 'IN'} ({', '.join(names)})"
    key = f"{prefix}_{len(parameters)}"
    parameters[key] = _normalize_value(item.value)
    symbol = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[item.operator]
    return f"{column} {symbol} :{key}"


def _refs(expression: str, stages: dict[str, MetricPlanStage]) -> list[tuple[str, str]]:
    parsed = sqlglot.parse_one(expression)
    refs = []
    for column in parsed.find_all(exp.Column):
        stage = stages.get(column.table)
        outputs = {field.name for field in stage.group_by} | {item.name for item in stage.aggregates} if stage else set()
        if column.table not in stages or not column.name or column.name not in outputs:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Output references must use stage.measure names")
        refs.append((column.table, column.name))
    if not refs:
        raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Output expression must reference a stage measure")
    return refs


def _output_expression(expression: str, stages: list[str], dialect: str) -> str:
    parsed = sqlglot.parse_one(expression)
    for column in list(parsed.find_all(exp.Column)):
        if column.table not in stages:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Output references an undeclared stage")
        replacement = exp.column(column.name, table=column.table, quoted=True)
        if column is parsed:
            parsed = replacement
        else:
            column.replace(replacement)
    for division in parsed.find_all(exp.Div):
        denominator = division.expression.copy()
        division.set("expression", exp.func("NULLIF", denominator, exp.Literal.number(0)))
        division.set("this", _cast_dividend(division.this, dialect))
    return parsed.sql(dialect=dialect)


def _time_bucket(column: str, grain: str, dialect: str) -> str:
    if dialect == "sqlite":
        formats = {"day": "%Y-%m-%d", "week": "%Y-%W", "month": "%Y-%m", "year": "%Y"}
        if grain == "quarter":
            return f"strftime('%Y', {column}) || '-Q' || ((cast(strftime('%m', {column}) as integer) + 2) / 3)"
        return f"strftime('{formats[grain]}', {column})"
    if dialect == "mysql":
        formats = {"day": "%Y-%m-%d", "week": "%x-%v", "month": "%Y-%m", "year": "%Y"}
        if grain == "quarter":
            return f"CONCAT(YEAR({column}), '-Q', QUARTER({column}))"
        return f"DATE_FORMAT({column}, '{formats[grain]}')"
    return f"DATE_TRUNC('{grain}', {column})"


def _cast_dividend(value: exp.Expression, dialect: str) -> exp.Cast:
    type_name = "REAL" if dialect == "sqlite" else "NUMERIC"
    return exp.Cast(this=value.copy(), to=exp.DataType.build(type_name))


def _null_safe_equal(left: str, right: str, dialect: str) -> str:
    if dialect == "mysql":
        return f"{left} <=> {right}"
    if dialect == "sqlite":
        return f"{left} IS {right}"
    return f"{left} IS NOT DISTINCT FROM {right}"
