"""Resolve metric drafts against canonical semantic metadata."""

from __future__ import annotations

import sqlglot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from src.models.db import SemanticColumnModel
from src.models.metric_definition import (
    MetricDefinition,
    MetricDiagnostic,
    MetricExpressionNode,
    MetricFilter,
    MetricGrain,
    MetricRatio,
    is_timestamp_diff_hours,
)
from src.services.metric_definitions import validate_metric_definition
from src.services.metric_hygiene import hygiene_flag_filters

_BINARY_KINDS: dict[type[exp.Expression], str] = {
    exp.Add: "add",
    exp.Sub: "sub",
    exp.Mul: "mul",
    exp.Div: "div",
}


class MetricDefinitionResolver:
    """Turn an untrusted metric draft into a canonical versioned definition."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def resolve(self, db_id: int, draft: MetricDefinition) -> MetricDefinition:
        """Resolve canonical identities, expression nodes, filters, and grain."""
        definition = draft.model_copy(deep=True)
        table = await validate_metric_definition(self._db, db_id, definition)
        columns = await _load_columns(self._db, table.id)
        by_name = {column.column_name.lower(): column for column in columns}
        definition.metric.filters = [
            *definition.metric.filters,
            *hygiene_flag_filters(
                [(column.column_name, column.data_type) for column in columns],
                {item.field for item in definition.metric.filters},
            ),
        ]
        formula = definition.metric.formula.model_copy(
            update={
                "expression_ast": _expression_tree(definition.metric.formula.expression, by_name),
                "ratio": _resolve_ratio(definition.metric.formula.ratio, by_name),
            }
        )
        filters = _resolve_filters(definition.metric.filters, by_name)
        grain = MetricGrain(column_ids=_primary_key_ids(table.primary_key_column, columns))
        diagnostics = _grain_diagnostics(grain)
        status = "needs_review" if diagnostics else definition.metric.status
        metric = definition.metric.model_copy(
            update={
                "formula": formula,
                "filters": filters,
                "base_entity": table.table_name,
                "base_entity_id": table.id,
                "grain": grain,
                "status": status,
            }
        )
        return MetricDefinition(schema_version=2, metric=metric, diagnostics=diagnostics)


async def _load_columns(db: AsyncSession, table_id: int) -> list[SemanticColumnModel]:
    result = await db.execute(select(SemanticColumnModel).where(SemanticColumnModel.table_id == table_id))
    return list(result.scalars().all())


def _primary_key_ids(primary_key: str | None, columns: list[SemanticColumnModel]) -> list[int]:
    flagged = [column.id for column in columns if column.is_primary_key]
    if flagged:
        return flagged
    target = (primary_key or "").lower()
    return [column.id for column in columns if column.column_name.lower() == target]


def _grain_diagnostics(grain: MetricGrain) -> list[MetricDiagnostic]:
    if grain.column_ids:
        return []
    return [MetricDiagnostic(code="MISSING_GRAIN", message="Base entity has no canonical primary-key grain")]


def _resolve_ratio(ratio: MetricRatio | None, columns: dict[str, SemanticColumnModel]) -> MetricRatio | None:
    if ratio is None:
        return None
    aggregates = {}
    for side in ("numerator", "denominator"):
        aggregate = getattr(ratio, side)
        aggregates[side] = aggregate.model_copy(
            update={
                "expression_ast": _expression_tree(aggregate.expression, columns),
                "filters": _resolve_filters(aggregate.filters, columns),
            }
        )
    return ratio.model_copy(update=aggregates)


def _resolve_filters(
    filters: list[MetricFilter],
    columns: dict[str, SemanticColumnModel],
) -> list[MetricFilter]:
    return [
        item.model_copy(
            update={"field": columns[item.field.lower()].column_name, "column_id": columns[item.field.lower()].id}
        )
        for item in filters
    ]


def _expression_tree(
    expression: str,
    columns: dict[str, SemanticColumnModel],
) -> MetricExpressionNode:
    return expression_tree_for_columns(expression, {name: column.id for name, column in columns.items()})


def expression_tree_for_columns(expression: str, columns: dict[str, int]) -> MetricExpressionNode:
    """Build a canonical AST from an expression and a case-insensitive column-ID map."""
    if expression == "*":
        return MetricExpressionNode(kind="literal", value=1)
    return _node(sqlglot.parse_one(expression), {name.lower(): column_id for name, column_id in columns.items()})


def _node(node: exp.Expression, columns: dict[str, int]) -> MetricExpressionNode:
    if is_timestamp_diff_hours(node):
        return MetricExpressionNode(
            kind="timestamp_diff_hours",
            children=[_node(item, columns) for item in node.expressions],
        )
    if isinstance(node, exp.Column):
        return MetricExpressionNode(kind="column", column_id=columns[node.name.lower()])
    if isinstance(node, exp.Literal):
        return MetricExpressionNode(kind="literal", value=float(node.this))
    if isinstance(node, exp.Paren):
        return _node(node.this, columns)
    if isinstance(node, exp.Neg):
        return MetricExpressionNode(kind="neg", children=[_node(node.this, columns)])
    for node_type, kind in _BINARY_KINDS.items():
        if isinstance(node, node_type):
            children = [_node(node.this, columns), _node(node.expression, columns)]
            return MetricExpressionNode(kind=kind, children=children)
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")
