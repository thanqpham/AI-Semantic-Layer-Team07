"""Pure SQL-text builders for the semantic query compiler (no DB access)."""

from __future__ import annotations

import re
from datetime import date, datetime
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
from src.services.semantic_compile_error import SemanticCompileError


def validate_read_only(sql: str, dialect: str | None = None) -> bool:
    """Require exactly one SELECT without write-capable AST nodes."""
    return trace_value("sql_guardrail", {"sql_length": len(sql)}, lambda: _validate_read_only(sql, dialect))


def _validate_read_only(sql: str, dialect: str | None = None) -> bool:
    """Validate the SQL AST without coupling parsing to tracing."""
    try:
        statements = sqlglot.parse(sql, read=dialect, error_level=sqlglot.ErrorLevel.RAISE)
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"Invalid SQL: {exc}") from exc
    if len(statements) != 1:
        raise ValueError("Multi-statement queries are not allowed")
    if not isinstance(statements[0], exp.Select):
        raise ValueError(f"Only SELECT statements are allowed, got {type(statements[0]).__name__}")
    parsed = statements[0]
    if parsed.find(exp.Into):
        raise ValueError("SELECT INTO is not allowed")
    dml = (exp.Insert, exp.Update, exp.Delete)
    if any(isinstance(node, dml) for node in parsed.walk()):
        raise ValueError("CTE containing DML is not allowed")
    ddl = (exp.Drop, exp.Alter, exp.TruncateTable)
    if any(isinstance(node, ddl) for node in parsed.walk()):
        raise ValueError("DDL is not allowed")
    if parsed.find(exp.Lock):
        raise ValueError("Locking clauses (FOR UPDATE/SHARE) are not allowed")
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
            definition, base.table_name, columns, column_types, dialect, parameters, f"metric_{metric.id}", residual
        )
        for metric, definition, residual in zip(metrics, definitions, residuals, strict=True)
    ]


def _assemble_sql(
    selections: list[str],
    base: SemanticTableModel,
    joins: list[dict[str, Any]],
    filters: list[dict[str, Any]],
    groups: list[str],
    dialect: str,
    parameters: dict[str, Any],
    limit: int,
    fixed: list[str],
    order_by: str | None = None,
) -> str:
    columns_clause = ",\n  ".join(selections)
    parts = [f"SELECT\n  {columns_clause}", f"FROM {_table_sql(base, dialect)}"]
    for join in joins:
        parts.append(_join_sql(join, dialect).strip())
    predicates = fixed + _runtime_predicates(filters, dialect, parameters)
    if predicates:
        where_clause = " AND ".join(predicates)
        parts.append(f"WHERE {where_clause}")
    if groups:
        groups_clause = ", ".join(groups)
        parts.append(f"GROUP BY {groups_clause}")
    if order_by:
        if not groups or len(selections) != 2:
            raise ValueError("Ordered dashboard queries require one metric and one dimension")
        if order_by == "metric_desc":
            metric_expression = selections[1].rsplit(" AS ", 1)[0]
            parts.append(f"ORDER BY ({metric_expression}) IS NULL, 2 DESC, 1 ASC")
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
        "data_type": column.data_type or "",
    }


def _raw_qualified(column: tuple[str, str]) -> str:
    return f"{column[0]}.{column[1]}"


def _quoted(name: str, dialect: str) -> str:
    return exp.to_identifier(name, quoted=True).sql(dialect=dialect)


def _qualified(table: str, column: str, dialect: str) -> str:
    return exp.column(column, table=table, quoted=True).sql(dialect=dialect)


def _table_sql(table: SemanticTableModel, dialect: str) -> str:
    return _table_name(table.physical_schema, table.table_name, dialect)


def _table_name(schema: str | None, table: str, dialect: str) -> str:
    if schema:
        return f"{_quoted(schema, dialect)}.{_quoted(table, dialect)}"
    return _quoted(table, dialect)


def _dimension_sql(item: dict[str, Any], dialect: str) -> str:
    column = _qualified(item["table_name"], item["column_name"], dialect)
    grain = item.get("time_grain")
    if not grain:
        return column
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


def _dimension_alias(item: dict[str, Any]) -> str:
    return f"dimension_{item['column_id']}"


def _compile_metric(
    definition: MetricDefinition,
    table: str,
    columns: dict[int, str],
    column_types: dict[int, str],
    dialect: str,
    parameters: dict[str, Any],
    alias: str,
    residual: list[MetricFilter],
) -> str:
    formula = definition.metric.formula
    if formula.ratio is not None:
        return _compile_ratio(
            formula.ratio, residual, table, columns, column_types, dialect, parameters, alias
        )
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
    table: str,
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
    cast_type = "REAL" if dialect == "sqlite" else "NUMERIC"
    aggregate = (
        f"({ratio.offset} + {ratio.scale} * CAST(({numerator_sql}) AS {cast_type}) "
        f"/ NULLIF(({denominator_sql}), 0))"
    )
    return f"{aggregate} AS {_quoted(alias, dialect)}"


def _compile_aggregate(
    aggregate: MetricAggregate,
    scope_filters: list[MetricFilter],
    table: str,
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
            {"field": item.field, "value": item.value},
        )
    return item.model_copy(update={"field": columns[item.column_id]})


def _compile_argument(
    node: MetricExpressionNode | None,
    table: str,
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
    table: str,
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
    parsed = sqlglot.parse_one(condition, read=dialect)
    allowed = (exp.EQ, exp.Column, exp.Identifier)
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


def _runtime_predicates(filters: list[dict[str, Any]], dialect: str, parameters: dict[str, Any]) -> list[str]:
    return [
        _predicate(
            item["table_name"],
            MetricFilter(field=item["column_name"], operator=item["operator"], value=item["value"]),
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
    if item.operator == "is_null":
        return f"{column} IS NULL"
    if item.operator == "is_not_null":
        return f"{column} IS NOT NULL"
    if item.operator in {"in", "not_in"}:
        values = [_coerce_literal(value, data_type) for value in item.value]
        names = [_bind(parameters, prefix, value) for value in values]
        keyword = "IN" if item.operator == "in" else "NOT IN"
        return f"{column} {keyword} ({', '.join(names)})"
    symbols = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    value = _coerce_literal(item.value, data_type)
    return f"{column} {symbols[item.operator]} {_bind(parameters, prefix, value)}"


_INT_TYPES = {"INTEGER", "INT", "BIGINT", "SMALLINT", "NUMERIC", "BIT", "BOOLEAN", "BOOL"}
_FLOAT_TYPES = {"FLOAT", "REAL", "DOUBLE", "DOUBLE PRECISION", "DECIMAL"}


def _coerce_literal(value: Any, data_type: str | None) -> Any:
    """Coerce string filter values to the column's numeric type; fail open."""
    if not isinstance(value, str) or not data_type:
        return value
    dt = data_type.upper()
    text = value.strip()
    try:
        if dt in _INT_TYPES:
            return int(text)
        if dt in _FLOAT_TYPES:
            return float(text)
    except ValueError:
        return value
    return value


def _normalize_value(value: Any) -> Any:
    """Coerce ISO date/datetime strings to date/datetime objects for strict DB drivers."""
    if not isinstance(value, str):
        return value
    val = value.strip()
    if len(val) == 10 and val[4] == "-" and val[7] == "-":
        try:
            return date.fromisoformat(val)
        except ValueError:
            return value
    if len(val) >= 19 and val[4] == "-" and val[7] == "-" and (val[10] in ("T", " ")):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _bind(parameters: dict[str, Any], prefix: str, value: Any) -> str:
    name = f"{prefix}_{len(parameters)}"
    parameters[name] = _normalize_value(value)
    return f":{name}"
