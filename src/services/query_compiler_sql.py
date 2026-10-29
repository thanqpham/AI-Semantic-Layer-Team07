"""Pure SQL-text builders for the semantic query compiler (no DB access)."""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from src.models.db import SemanticColumnModel, SemanticMetricModel, SemanticTableModel
from src.models.metric_definition import (
    MetricAggregate,
    MetricDefinition,
    MetricExpressionNode,
    MetricFilter,
    MetricRatio,
)
from src.observability import trace_value
from src.services.query_compiler_dialect import time_bucket_sql
from src.services.query_compiler_parameters import (
    bind_coerced_parameter,
    bind_coerced_sequence,
    coerce_filter_value,
    validate_null_filter_value,
)
from src.services.semantic_compile_error import SemanticCompileError


def validate_read_only(sql: str, dialect: str | None = None) -> bool:
    """Require exactly one SELECT without write-capable AST nodes."""
    return trace_value("sql_guardrail", {"sql_length": len(sql)}, lambda: _validate_read_only(sql, dialect))


def _validate_read_only(sql: str, dialect: str | None = None) -> bool:
    """Validate the SQL AST without coupling parsing to tracing."""
    try:
        statements = sqlglot.parse(sql, read=dialect, error_level=sqlglot.ErrorLevel.RAISE)
    except sqlglot.errors.ParseError as exc:
        raise SemanticCompileError("invalid_sql", f"Invalid SQL: {exc}") from exc
    if len(statements) != 1:
        raise SemanticCompileError("multi_statement", "Multi-statement queries are not allowed")
    if not isinstance(statements[0], exp.Select):
        raise SemanticCompileError(
            "read_only_violation", f"Only SELECT statements are allowed, got {type(statements[0]).__name__}"
        )
    parsed = statements[0]
    if parsed.find(exp.Into):
        raise SemanticCompileError("read_only_violation", "SELECT INTO is not allowed")
    dml = (exp.Insert, exp.Update, exp.Delete)
    if any(isinstance(node, dml) for node in parsed.walk()):
        raise SemanticCompileError("read_only_violation", "CTE containing DML is not allowed")
    ddl = (exp.Drop, exp.Alter, exp.TruncateTable)
    if any(isinstance(node, ddl) for node in parsed.walk()):
        raise SemanticCompileError("read_only_violation", "DDL is not allowed")
    if parsed.find(exp.Lock):
        raise SemanticCompileError("read_only_violation", "Locking clauses (FOR UPDATE/SHARE) are not allowed")
    return True


def _dimension_expressions(dimensions: list[dict[str, Any]], dialect: str) -> tuple[list[str], list[str]]:
    group_sql = [_dimension_sql(item, dialect) for item in dimensions]
    select_sql = [
        f"{expression} AS {_quoted(_dimension_alias(item), dialect)}"
        for expression, item in zip(group_sql, dimensions, strict=True)
    ]
    return select_sql, group_sql


def _metric_expressions(
    metrics: list[SemanticMetricModel],
    definitions: list[MetricDefinition],
    base: SemanticTableModel,
    columns: dict[int, str],
    column_types: dict[int, str],
    dialect: str,
    parameters: dict[str, Any],
    residuals: list[list[MetricFilter]],
) -> list[str]:
    return [
        _compile_metric(
            definition,
            (base.physical_schema, base.table_name),
            columns,
            column_types,
            dialect,
            parameters,
            f"metric_{metric.id}",
            residual,
        )
        for metric, definition, residual in zip(metrics, definitions, residuals, strict=True)
    ]


def _assemble_sql(
    selections: list[str],
    base: SemanticTableModel,
    joins: list[dict[str, Any]],
    filters: list[dict[str, Any]],
    exists_filters: list[dict[str, Any]],
    groups: list[str],
    dialect: str,
    parameters: dict[str, Any],
    limit: int,
    fixed: list[str],
    order_by: str | None = None,
    sort_metric_position: int | None = None,
) -> str:
    columns_clause = ",\n  ".join(selections)
    parts = [f"SELECT\n  {columns_clause}", f"FROM {_table_sql(base, dialect)}"]
    for join in joins:
        parts.append(_join_sql(join, dialect).strip())
    predicates = fixed + _runtime_predicates(filters, dialect, parameters)
    predicates.extend(_exists_predicates(exists_filters, base, dialect, parameters))
    if predicates:
        where_clause = " AND ".join(predicates)
        parts.append(f"WHERE {where_clause}")
    if groups:
        groups_clause = ", ".join(groups)
        parts.append(f"GROUP BY {groups_clause}")
    if order_by:
        if not groups or len(selections) < 2:
            raise ValueError("Ordered dashboard queries require one metric and one dimension")
        if order_by == "metric_desc":
            metric_position = sort_metric_position or 2
            if metric_position < 2 or metric_position > len(selections):
                raise ValueError("Sort metric position must select a metric output")
            metric_expression = selections[metric_position - 1].rsplit(" AS ", 1)[0]
            parts.append(f"ORDER BY ({metric_expression}) IS NULL, {metric_position} DESC, 1 ASC")
        else:
            dimension_expression = selections[0].rsplit(" AS ", 1)[0]
            parts.append(f"ORDER BY ({dimension_expression}) IS NULL, 1 DESC")
    parts.append(f"LIMIT {limit}")
    return "\n".join(parts)


def _join_sql(join: dict[str, Any], dialect: str) -> str:
    condition = _validated_join_condition(join["condition"], dialect)
    table = _table_name(join["physical_schema"], join["table_name"], dialect)
    return f" JOIN {table} ON {condition}"


def _column_info(column: SemanticColumnModel, table: SemanticTableModel) -> dict[str, Any]:
    dt = (column.data_type or "").upper()
    is_time = column.is_time_dimension or any(t in dt for t in ("DATE", "TIME", "TIMESTAMP", "DATETIME"))
    return {
        "column_id": column.id,
        "column_name": column.column_name,
        "business_name": column.business_name,
        "is_time_dimension": is_time,
        "table_id": table.id,
        "table_name": table.table_name,
        "physical_schema": table.physical_schema,
        "data_type": column.data_type or "",
    }


def _raw_qualified(column: tuple[str, str]) -> str:
    return f"{column[0]}.{column[1]}"


def _quoted(name: str, dialect: str) -> str:
    return exp.to_identifier(name, quoted=True).sql(dialect=dialect)


def _qualified(table: str | tuple[str | None, str], column: str, dialect: str) -> str:
    schema, table_name = table if isinstance(table, tuple) else (None, table)
    return exp.column(column, table=table_name, db=schema, quoted=True).sql(dialect=dialect)


def _table_sql(table: SemanticTableModel, dialect: str) -> str:
    return _table_name(table.physical_schema, table.table_name, dialect)


def _table_name(schema: str | None, table: str, dialect: str) -> str:
    if schema:
        return f"{_quoted(schema, dialect)}.{_quoted(table, dialect)}"
    return _quoted(table, dialect)


def _dimension_sql(item: dict[str, Any], dialect: str) -> str:
    column = _qualified((item.get("physical_schema"), item["table_name"]), item["column_name"], dialect)
    grain = item.get("time_grain")
    if not grain:
        return column
    return time_bucket_sql(column, grain, dialect, item.get("data_type") or "")


def _dimension_alias(item: dict[str, Any]) -> str:
    return f"dimension_{item['column_id']}"


def _compile_metric(
    definition: MetricDefinition,
    table: str | tuple[str | None, str],
    columns: dict[int, str],
    column_types: dict[int, str],
    dialect: str,
    parameters: dict[str, Any],
    alias: str,
    residual: list[MetricFilter],
) -> str:
    formula = definition.metric.formula
    if formula.ratio is not None:
        return _compile_ratio(formula.ratio, residual, table, columns, column_types, dialect, parameters, alias)
    if _tree_contains_division(formula.expression_ast):
        raise SemanticCompileError(
            "METRIC_NEEDS_REVIEW",
            "Division metrics require explicit numerator and denominator aggregations",
        )
    predicates = [
        _predicate(
            table, _resolved_filter(item, columns), dialect, parameters, "metric", column_types.get(item.column_id)
        )
        for item in residual
    ]
    condition = " AND ".join(predicates)
    argument = _compile_argument(formula.expression_ast, table, columns, dialect)
    if condition:
        inner = argument if argument != "*" else "1"
        conditional = f"CASE WHEN {condition} THEN {inner} END"
    else:
        conditional = argument
    if formula.function == "COUNT_DISTINCT":
        aggregate = f"COUNT(DISTINCT {conditional})"
    else:
        aggregate = f"{formula.function}({conditional})"
    return f"{aggregate} AS {_quoted(alias, dialect)}"


def _compile_ratio(
    ratio: MetricRatio,
    scope_filters: list[MetricFilter],
    table: str | tuple[str | None, str],
    columns: dict[int, str],
    column_types: dict[int, str],
    dialect: str,
    parameters: dict[str, Any],
    alias: str,
) -> str:
    """Compile separate aggregate expressions and filters for both ratio sides."""
    numerator_sql = _compile_aggregate(
        ratio.numerator, scope_filters, table, columns, column_types, dialect, parameters, "ratio_num"
    )
    denominator_sql = _compile_aggregate(
        ratio.denominator, scope_filters, table, columns, column_types, dialect, parameters, "ratio_den"
    )
    cast_type = {"sqlite": "REAL", "mysql": "DECIMAL(65, 30)"}.get(dialect, "NUMERIC")
    aggregate = (
        f"({ratio.offset} + {ratio.scale} * CAST(({numerator_sql}) AS {cast_type}) / NULLIF(({denominator_sql}), 0))"
    )
    return f"{aggregate} AS {_quoted(alias, dialect)}"


def _compile_aggregate(
    aggregate: MetricAggregate,
    scope_filters: list[MetricFilter],
    table: str | tuple[str | None, str],
    columns: dict[int, str],
    column_types: dict[int, str],
    dialect: str,
    parameters: dict[str, Any],
    prefix: str,
) -> str:
    filters = [*scope_filters, *aggregate.filters]
    predicates = [
        _predicate(
            table, _resolved_filter(item, columns), dialect, parameters, prefix, column_types.get(item.column_id)
        )
        for item in filters
    ]
    argument = _compile_argument(aggregate.expression_ast, table, columns, dialect)
    if predicates:
        value = argument if argument != "*" else "1"
        argument = f"CASE WHEN {' AND '.join(predicates)} THEN {value} END"
    if aggregate.function == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {argument})"
    return f"{aggregate.function}({argument})"


def _tree_contains_division(node: MetricExpressionNode | None) -> bool:
    return node is not None and (node.kind == "div" or any(_tree_contains_division(child) for child in node.children))


_COLUMN_REFERENCE_PATTERN = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_]\w*$")


def _resolved_filter(item: MetricFilter, columns: dict[int, str]) -> MetricFilter:
    if item.column_id not in columns:
        raise SemanticCompileError(
            "UNKNOWN_REFERENCE",
            "Metric filter contains an unknown column",
            {"column_id": item.column_id},
        )
    if isinstance(item.value, str) and _COLUMN_REFERENCE_PATTERN.fullmatch(item.value):
        raise SemanticCompileError(
            "INVALID_FILTER_VALUE",
            "Metric filter value is a column reference, not a literal",
            {"field": item.field, "column_id": item.column_id},
        )
    return item.model_copy(update={"field": columns[item.column_id]})


def _compile_argument(
    node: MetricExpressionNode | None,
    table: str | tuple[str | None, str],
    columns: dict[int, str],
    dialect: str,
) -> str:
    if node is None:
        raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Metric expression is not resolved")
    if node.kind == "column" and node.column_id in columns:
        return _qualified(table, columns[node.column_id], dialect)
    if node.kind == "literal":
        return str(node.value)
    if node.kind == "neg":
        return f"-({_compile_argument(node.children[0], table, columns, dialect)})"
    if node.kind == "timestamp_diff_hours":
        return _compile_timestamp_difference(node, table, columns, dialect)
    left = _compile_argument(node.children[0], table, columns, dialect)
    right = _compile_argument(node.children[1], table, columns, dialect)
    if node.kind == "div":
        return f"(CAST({left} AS DECIMAL) / NULLIF({right}, 0))"
    operators = {"add": "+", "sub": "-", "mul": "*"}
    if node.kind in operators:
        return f"({left} {operators[node.kind]} {right})"
    raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric expression contains an unknown column")


def _compile_timestamp_difference(
    node: MetricExpressionNode,
    table: str | tuple[str | None, str],
    columns: dict[int, str],
    dialect: str,
) -> str:
    """Render the fixed timestamp-difference primitive for one SQL dialect."""
    if len(node.children) != 2:
        raise SemanticCompileError("METRIC_NEEDS_REVIEW", "Timestamp difference requires two resolved columns")
    end, start = (_compile_argument(item, table, columns, dialect) for item in node.children)
    if dialect == "sqlite":
        return f"(julianday({end}) - julianday({start})) * 24.0"
    if dialect == "mysql":
        return f"TIMESTAMPDIFF(SECOND, {start}, {end}) / 3600.0"
    return f"EXTRACT(EPOCH FROM ({end} - {start})) / 3600.0"


def _validated_join_condition(condition: str, dialect: str) -> str:
    parsed = sqlglot.parse_one(condition)
    allowed = (exp.And, exp.EQ, exp.Column, exp.Identifier)
    if any(not isinstance(node, allowed) for node in parsed.walk()):
        raise ValueError("Unsafe join condition in semantic metadata")
    for column in parsed.find_all(exp.Column):
        column.set("this", exp.to_identifier(column.name, quoted=True))
        column.set("table", exp.to_identifier(column.table, quoted=True))
    return parsed.sql(dialect=dialect)


def _shared_filters(definitions: list[MetricDefinition]) -> list[MetricFilter]:
    """Filters present (same field/operator/value/column) in every metric definition."""
    if not definitions:
        return []
    others = [{(f.field, f.operator, repr(f.value), f.column_id) for f in d.metric.filters} for d in definitions[1:]]
    return [
        f
        for f in definitions[0].metric.filters
        if all((f.field, f.operator, repr(f.value), f.column_id) in keys for keys in others)
    ]


def _residual_filters(definition: MetricDefinition, shared: list[MetricFilter]) -> list[MetricFilter]:
    """Filters of one definition that are not part of the shared (hoisted) set."""
    shared_keys = {(f.field, f.operator, repr(f.value), f.column_id) for f in shared}
    return [
        f for f in definition.metric.filters if (f.field, f.operator, repr(f.value), f.column_id) not in shared_keys
    ]


def _fixed_predicates(
    shared: list[MetricFilter],
    columns: dict[int, str],
    column_types: dict[int, str],
    table: str,
    dialect: str,
    parameters: dict[str, Any],
) -> list[str]:
    """Compile hoisted shared predicates for the WHERE clause (prefix 'fixed')."""
    return [
        _predicate(
            table, _resolved_filter(item, columns), dialect, parameters, "fixed", column_types.get(item.column_id)
        )
        for item in shared
    ]


def _exists_predicates(
    filters: list[dict[str, Any]], base: SemanticTableModel, dialect: str, parameters: dict[str, Any]
) -> list[str]:
    grouped: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    for item in filters:
        key = tuple(step["relationship_id"] for step in item["path"])
        grouped.setdefault(key, []).append(item)
    return [_exists_predicate(items, base, dialect, parameters) for items in grouped.values()]


def _exists_predicate(
    items: list[dict[str, Any]], base: SemanticTableModel, dialect: str, parameters: dict[str, Any]
) -> str:
    path = items[0]["path"]
    first = path[0]
    target = first["pairs"][0][1]
    alias = _quoted(f"t_{first['to_table_id']}", dialect)
    parts = [f"SELECT 1 FROM {_table_name(target[0], target[1], dialect)} AS {alias}"]  # noqa: S608
    conditions = _step_conditions(first, base.id, first["to_table_id"], base, dialect)
    for step in path[1:]:
        target = step["pairs"][0][1]
        next_alias = _quoted(f"t_{step['to_table_id']}", dialect)
        parts.append(
            f"JOIN {_table_name(target[0], target[1], dialect)} AS {next_alias} ON "
            + " AND ".join(_step_conditions(step, step["from_table_id"], step["to_table_id"], base, dialect))
        )
    conditions.extend(_exists_filter_predicate(item["filter"], dialect, parameters) for item in items)
    return f"EXISTS ({' '.join(parts)} WHERE {' AND '.join(conditions)})"


def _step_conditions(
    step: dict[str, Any], base_id: int, target_id: int, base: SemanticTableModel, dialect: str
) -> list[str]:
    return [
        f"{_exists_column(left, step['from_table_id'], base_id, base, dialect)} = "
        f"{_exists_column(right, target_id, base_id, base, dialect)}"
        for left, right in step["pairs"]
    ]


def _exists_column(
    column: tuple[str | None, str, str], table_id: int, base_id: int, base: SemanticTableModel, dialect: str
) -> str:
    table = (base.physical_schema, base.table_name) if table_id == base_id else f"t_{table_id}"
    return _qualified(table, column[2], dialect)


def _exists_filter_predicate(item: dict[str, Any], dialect: str, parameters: dict[str, Any]) -> str:
    return _predicate(
        f"t_{item['table_id']}",
        MetricFilter.model_construct(field=item["column_name"], operator=item["operator"], value=item["value"]),
        dialect,
        parameters,
        "runtime",
        item["data_type"],
    )


def _runtime_predicates(filters: list[dict[str, Any]], dialect: str, parameters: dict[str, Any]) -> list[str]:
    return [
        _predicate(
            (item.get("physical_schema"), item["table_name"]),
            MetricFilter.model_construct(field=item["column_name"], operator=item["operator"], value=item["value"]),
            dialect,
            parameters,
            "runtime",
            item["data_type"],
        )
        for item in filters
    ]


def _predicate(
    table: str,
    item: MetricFilter,
    dialect: str,
    parameters: dict[str, Any],
    prefix: str,
    data_type: str | None = None,
) -> str:
    column = _qualified(table, item.field, dialect)
    column_type = data_type or ""
    if item.operator == "is_null":
        validate_null_filter_value(item.value, column_type, dialect)
        return f"{column} IS NULL"
    if item.operator == "is_not_null":
        validate_null_filter_value(item.value, column_type, dialect)
        return f"{column} IS NOT NULL"
    if item.operator in {"in", "not_in"}:
        names = bind_coerced_sequence(item.value, column_type, dialect, parameters, prefix)
        keyword = "IN" if item.operator == "in" else "NOT IN"
        return f"{column} {keyword} ({', '.join(names)})"
    if item.operator == "between":
        names = bind_coerced_sequence(item.value, column_type, dialect, parameters, prefix, expected_length=2)
        return f"{column} BETWEEN {names[0]} AND {names[1]}"
    symbols = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    placeholder = bind_coerced_parameter(item.value, column_type, dialect, parameters, prefix)
    return f"{column} {symbols[item.operator]} {placeholder}"


def _coerce_literal(value: Any, data_type: str | None, dialect: str = "postgres") -> Any:
    """Delegate scalar literal coercion to coerce_filter_value."""
    return coerce_filter_value(value, data_type or "", dialect)
