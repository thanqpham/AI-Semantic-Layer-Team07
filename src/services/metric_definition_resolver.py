"""Resolve metric drafts against canonical semantic metadata."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from src.models.db import SemanticColumnModel, SemanticTableModel
from src.models.metric_definition import (
    MetricDefinition,
    MetricDiagnostic,
    MetricExpressionNode,
    MetricFilter,
    MetricGrain,
    MetricPlanFilter,
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
        if definition.metric.query_plan is None:
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
        if definition.metric.query_plan is not None:
            await _resolve_plan_column_ids(self._db, db_id, definition.metric.query_plan, definition.metric.filters)
            filters = definition.metric.filters
        else:
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
        return MetricDefinition(schema_version=3 if metric.query_plan else 2, metric=metric, diagnostics=diagnostics)


async def _load_columns(db: AsyncSession, table_id: int) -> list[SemanticColumnModel]:
    result = await db.execute(select(SemanticColumnModel).where(SemanticColumnModel.table_id == table_id))
    return list(result.scalars().all())


async def _resolve_plan_column_ids(
    db: AsyncSession, db_id: int, plan: Any, metric_filters: list[MetricFilter] | None = None
) -> None:
    """Replace user supplied column IDs with IDs resolved from the metadata store."""
    tables_result = await db.execute(select(SemanticTableModel).where(SemanticTableModel.db_id == db_id))
    tables = {table.table_name.casefold(): table for table in tables_result.scalars().all()}
    columns = {table.id: await _load_columns(db, table.id) for table in tables.values()}
    stage_outputs: dict[str, dict[str, int | None]] = {}
    physical_stages = [stage for stage in plan.stages if stage.base_entity]
    available_tables: list[set[str]] = []
    for stage in physical_stages:
        available_tables.append({stage.base_entity.casefold(), *(name.casefold() for name in stage.joins)})
    for stage in plan.stages:
        if stage.source_stage:
            parent = stage_outputs[stage.source_stage]
            for field in stage.group_by:
                field.column_id = parent.get(field.expression.split(".", 1)[-1])
            stage_outputs[stage.name] = {
                **{field.name: field.column_id for field in stage.group_by},
                **{item.name: None for item in stage.aggregates},
            }
            continue
        base = tables.get(stage.base_entity.casefold())
        if base is None:
            raise ValueError(f"Unknown metric plan source: {stage.base_entity}")
        allowed = {base.table_name.casefold(), *(name.casefold() for name in stage.joins)}

        def resolve(
            expression: str, base: SemanticTableModel = base, allowed: set[str] = allowed
        ) -> tuple[str, SemanticColumnModel]:
            parsed = sqlglot.parse_one(expression)
            if not isinstance(parsed, exp.Column):
                raise ValueError(f"Metric plan field must be a column: {expression}")
            table_name = parsed.table.casefold() if parsed.table else base.table_name.casefold()
            if table_name not in allowed:
                raise ValueError(f"Metric plan field uses an undeclared joined table: {expression}")
            table = tables.get(table_name)
            column = (
                next(
                    (item for item in columns[table.id] if item.column_name.casefold() == parsed.name.casefold()), None
                )
                if table
                else None
            )
            if table is None or column is None:
                raise ValueError(f"Unknown metric plan column: {expression}")
            return table.table_name, column

        for field in stage.group_by:
            table_name, column = resolve(field.expression)
            field.expression = f"{table_name}.{column.column_name}"
            field.column_id = column.id
        stage_outputs[stage.name] = {
            **{field.name: field.column_id for field in stage.group_by},
            **{item.name: None for item in stage.aggregates},
        }
        for item in [
            *stage.filters,
            *(filter_item for aggregate in stage.aggregates for filter_item in aggregate.filters),
        ]:
            try:
                table_name, column = resolve(item.field)
            except ValueError:
                continue
            item.field = f"{table_name}.{column.column_name}"
            item.column_id = column.id
        for table_name in {base.table_name.casefold(), *(name.casefold() for name in stage.joins)}:
            joined_table = tables.get(table_name)
            if joined_table is None:
                continue
            table_columns = columns[joined_table.id]
            existing_names = {
                item.field.split(".", 1)[1].casefold()
                for item in stage.filters
                if "." in item.field and item.field.split(".", 1)[0].casefold() == table_name
            }
            for item in hygiene_flag_filters(
                [(column.column_name, column.data_type) for column in table_columns], existing_names
            ):
                column = next(
                    column for column in table_columns if column.column_name.casefold() == item.field.casefold()
                )
                stage.filters.append(
                    MetricPlanFilter(
                        field=f"{joined_table.table_name}.{column.column_name}",
                        column_id=column.id,
                        operator=item.operator,
                        value=item.value,
                    )
                )
    if metric_filters:
        common_tables = set.intersection(*available_tables) if available_tables else set()
        for item in metric_filters:
            matches = [
                column
                for table_name in common_tables
                if (table := tables.get(table_name)) is not None
                for column in columns[table.id]
                if column.column_name.casefold() == item.field.casefold()
            ]
            if len(matches) != 1:
                raise ValueError(f"Metric plan scope filter must map to one common source column: {item.field}")
            item.column_id = matches[0].id


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
