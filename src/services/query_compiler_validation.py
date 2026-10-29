"""Validate persisted metric definitions and selected time grains."""

from __future__ import annotations

from typing import Any

from src.models.db import SemanticMetricModel
from src.models.metric_definition import MetricDefinition, MetricExpressionNode
from src.models.schemas import DimensionSelection
from src.services.metric_definition_resolver import expression_tree_for_columns
from src.services.metric_definitions import is_numeric_data_type
from src.services.semantic_compile_error import SemanticCompileError


def canonical_definitions(metrics: list[SemanticMetricModel]) -> list[MetricDefinition]:
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


def validate_definition_asts(
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


def apply_time_grains(dimensions: list[dict[str, Any]], selections: list[DimensionSelection]) -> None:
    for dimension, selection in zip(dimensions, selections, strict=True):
        dimension["time_grain"] = selection.time_grain
        if selection.time_grain and not dimension["is_time_dimension"]:
            raise SemanticCompileError(
                "INVALID_TIME_GRAIN",
                f"Column {selection.column_id} is not a time dimension",
                {"column_id": selection.column_id},
            )
