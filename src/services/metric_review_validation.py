"""Validate draft metrics using metadata only, including the compiler's actual AST."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import sqlglot
from sqlglot import exp

from src.models.metric_definition import MetricDefinition, MetricFilter
from src.models.metric_review import MetricReview, ReviewIssue
from src.services.metric_definition_resolver import _node
from src.services.metric_definitions import _validate_expression_columns, _validate_filter_columns
from src.services.metric_hygiene import hygiene_flag_filters


def schema_tables(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept existing map and list metadata envelopes."""
    tables = schema.get("tables", schema)
    if isinstance(tables, list):
        return tables
    return [
        {**table, "table_name": table.get("table_name", name)}
        for name, table in tables.items()
        if isinstance(table, dict)
    ]


def technical_review(
    raw: dict[str, Any], context: dict[str, Any]
) -> tuple[MetricDefinition | None, MetricReview | None]:
    """Canonicalize hygiene and reject drafts the existing compiler cannot represent."""
    try:
        definition = _parse_definition(raw)
        _validate_schema(definition, context["schema"])
        definition.metric.status = "pending_approval"
        definition.diagnostics = []
        return definition, None
    except (ValueError, KeyError, TypeError, sqlglot.errors.SqlglotError) as exc:
        message = str(exc)
        unsupported = "Unsupported expression" in message or "UNSUPPORTED_RATIO" in message or "DIVISION" in message
        issue = ReviewIssue(
            code="UNSUPPORTED" if unsupported else "INVALID_DEFINITION",
            message="Định nghĩa chưa hợp lệ.",
            evidence=message,
            action="Dùng công thức compiler hỗ trợ và đúng metadata; không đổi mục tiêu KPI.",
        )
        return None, MetricReview(
            status="unsupported" if unsupported else "needs_revision",
            summary="Kiểm tra kỹ thuật chưa đạt.",
            issues=[issue],
        )


def _parse_definition(raw: dict[str, Any]) -> MetricDefinition:
    spec = raw.get("metric", raw)
    if not isinstance(spec, dict):
        raise ValueError("metric phải là object.")
    raw_filters = spec.get("filters", [])
    if not isinstance(raw_filters, list):
        raise ValueError("filters phải là danh sách, không được bỏ qua điều kiện sai contract.")
    for item in raw_filters:
        MetricFilter.model_validate(item)
    return MetricDefinition.model_validate(raw)


def _validate_schema(definition: MetricDefinition, schema: dict[str, Any]) -> None:
    table = next(
        (t for t in schema_tables(schema) if t["table_name"].casefold() == definition.metric.base_entity.casefold()),
        None,
    )
    if table is None:
        raise ValueError("Bảng gốc không tồn tại trong schema.")
    definition.metric.base_entity = table["table_name"]
    columns = _columns(table)
    _validate_expression_columns(definition, columns)
    _validate_filter_columns(definition, columns)
    _validate_grain(columns)
    _validate_compiler_expression(definition, columns)
    definition.metric.filters.extend(
        hygiene_flag_filters(
            [(c.column_name, c.data_type) for c in columns.values()], {f.field for f in definition.metric.filters}
        )
    )
    _validate_filters(definition, columns)


def _columns(table: dict[str, Any]) -> dict[str, Any]:
    return {
        c.get("column_name", c.get("name")): SimpleNamespace(
            **{
                **c,
                "column_name": c.get("column_name", c.get("name")),
                "id": i,
                "data_type": c.get("data_type", ""),
                "is_primary_key": c.get("is_primary_key", False),
                "is_nullable": c.get("is_nullable", True),
                "allowed_values": c.get("allowed_values"),
            }
        )
        for i, c in enumerate(table.get("columns", []), 1)
    }


def _validate_grain(columns: dict[str, Any]) -> None:
    if not any(c.is_primary_key for c in columns.values()):
        raise ValueError("MISSING_GRAIN: chưa xác định khóa chính của bảng gốc.")


def _validate_compiler_expression(definition: MetricDefinition, columns: dict[str, Any]) -> None:
    formula = definition.metric.formula
    if formula.expression == "*":
        return
    parsed = sqlglot.parse_one(formula.expression)
    by_name = {name.casefold(): column for name, column in columns.items()}
    _node(parsed, by_name)
    for column in parsed.find_all(exp.Column):
        data_type = by_name[column.name.casefold()].data_type.upper()
        if formula.function in {"SUM", "AVG"} and any(t in data_type for t in ("BOOL", "BIT")):
            raise ValueError("SUM/AVG không hỗ trợ cột boolean hoặc bit.")
    for division in parsed.find_all(exp.Div):
        denominator = division.expression
        if any(
            by_name[c.name.casefold()].is_primary_key or c.name.casefold().endswith("_id")
            for c in division.find_all(exp.Column)
        ):
            raise ValueError("UNSUPPORTED_RATIO: không được chia khóa/ID để tạo KPI tỷ lệ.")
        if not isinstance(denominator, exp.Literal) or not denominator.is_number or float(denominator.this) == 0:
            raise ValueError("UNSAFE_DIVISION: mẫu số có thể bằng không; compiler chưa có primitive chia an toàn.")


def _validate_filters(definition: MetricDefinition, columns: dict[str, Any]) -> None:
    by_name = {name.casefold(): c for name, c in columns.items()}
    for item in definition.metric.filters:
        column = by_name[item.field.casefold()]
        item.field = column.column_name
        if item.operator in {"is_null", "is_not_null"}:
            continue
        values = item.value if item.operator in {"in", "not_in"} else [item.value]
        if not isinstance(values, list) or not values:
            raise ValueError("Filter IN cần danh sách giá trị không rỗng.")
        for value in values:
            _validate_filter_value(column, value)


def _validate_filter_value(column: Any, value: Any) -> None:
    dtype = column.data_type.upper()
    if value is None or isinstance(value, (dict, list)):
        raise ValueError(f"Filter {column.column_name} cần literal khác NULL.")
    if column.allowed_values and value not in column.allowed_values:
        raise ValueError(f"Giá trị filter {column.column_name} không có trong metadata khai báo.")
    if "BOOL" in dtype and not isinstance(value, bool):
        raise ValueError(f"Filter {column.column_name} cần true/false.")
    if any(t in dtype for t in ("INT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE", "REAL", "BIT")):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Filter {column.column_name} cần giá trị số.")
    if any(t in dtype for t in ("CHAR", "TEXT", "DATE", "TIME")) and not isinstance(value, str):
        raise ValueError(f"Filter {column.column_name} cần giá trị chuỗi.")
