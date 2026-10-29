"""Load and validate metadata used by semantic query compilation."""

from __future__ import annotations

from dataclasses import dataclass
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
from src.models.metric_definition import (
    MetricDefinition,
    MetricPlanField,
    MetricPlanFilter,
    MetricPlanStage,
    MetricQueryPlan,
)
from src.models.schemas import SemanticQueryFilter
from src.services.query_compiler_parameters import (
    coerce_filter_value,
    coerce_sequence_filter_values,
    validate_null_filter_value,
)
from src.services.query_compiler_plan import resolve_scoped_filter_stages
from src.services.query_compiler_sql import _column_info
from src.services.relationship_runtime import RelationshipStep, active_relationship_filters, filter_path, valid_pairs
from src.services.relationship_runtime import safe_join_path as _safe_join_path
from src.services.semantic_compile_error import SemanticCompileError


class QueryCompilerMetadata:
    """Resolve validated metric, table, column, and relationship metadata."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def load_dialect(self, connection_id: int) -> str:
        record = await self._db.get(SemanticDatabaseModel, connection_id)
        if record is None:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Semantic database not found")
        return {"postgresql": "postgres", "mysql": "mysql", "sqlite": "sqlite"}.get(record.db_type, record.db_type)

    async def load_metrics(self, db_id: int, ids: list[int]) -> list[SemanticMetricModel]:
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
    def require_same_base(definitions: list[MetricDefinition]) -> str:
        bases = {item.metric.base_entity for item in definitions}
        if len(bases) != 1:
            raise SemanticCompileError("INCOMPATIBLE_BASE_ENTITY", "All selected metrics must use the same base entity")
        return bases.pop()

    async def load_tables(self, db_id: int) -> list[SemanticTableModel]:
        result = await self._db.execute(select(SemanticTableModel).where(SemanticTableModel.db_id == db_id))
        return list(result.scalars().all())

    async def load_base_columns(self, table_id: int) -> dict[int, tuple[str, str]]:
        result = await self._db.execute(select(SemanticColumnModel).where(SemanticColumnModel.table_id == table_id))
        return {column.id: (column.column_name, column.data_type or "") for column in result.scalars().all()}

    async def load_dimensions(self, db_id: int, ids: list[int]) -> list[dict[str, Any]]:
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

    async def load_runtime_filters(self, db_id: int, filters: list[SemanticQueryFilter]) -> list[dict[str, Any]]:
        if not filters:
            return []
        columns = await self.load_dimensions(db_id, [item.column_id for item in filters])
        return [
            {**column, "operator": item.operator, "value": item.value}
            for column, item in zip(columns, filters, strict=True)
        ]

    async def resolve_joins(
        self,
        db_id: int,
        base: SemanticTableModel,
        dimensions: list[dict[str, Any]],
        tables: dict[int, SemanticTableModel],
    ) -> list[dict[str, Any]]:
        stmt = select(CanonicalRelationshipModel).where(
            CanonicalRelationshipModel.connection_id == db_id, *active_relationship_filters()
        )
        relationships = list((await self._db.execute(stmt)).scalars().all())
        column_names = await self._relationship_columns(relationships)
        joins: list[dict[str, Any]] = []
        joined = {base.id}
        for table_id in {item["table_id"] for item in dimensions} - joined:
            for rel in _safe_join_path(relationships, base.id, table_id):
                if rel.to_entity_id not in joined:
                    target = tables[rel.to_entity_id]
                    if any(tables[item].table_name.casefold() == target.table_name.casefold() for item in joined):
                        raise SemanticCompileError("UNSAFE_JOIN", "Join endpoints have ambiguous table names")
                    joins.append(
                        {
                            "relationship_id": rel.id,
                            "table_name": target.table_name,
                            "physical_schema": target.physical_schema,
                            "condition": _relationship_condition(rel, column_names),
                        }
                    )
                    joined.add(rel.to_entity_id)
        return joins

    async def resolve_runtime_filters(
        self, db_id: int, base: SemanticTableModel, filters: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Partition filters into safe WHERE predicates and fanout EXISTS paths."""
        result = await self._db.execute(
            select(CanonicalRelationshipModel).where(
                CanonicalRelationshipModel.connection_id == db_id, *active_relationship_filters()
            )
        )
        relationships = list(result.scalars().all())
        columns = await self._relationship_columns(relationships)
        direct, exists = [], []
        for item in filters:
            path = filter_path(relationships, base.id, item["table_id"])
            if _contains_fanout(path, relationships):
                exists.append(_exists_filter_record(item, path, columns))
            else:
                direct.append(item)
        return direct, exists

    async def _relationship_columns(
        self, relationships: list[CanonicalRelationshipModel]
    ) -> dict[int, tuple[str | None, str, str]]:
        ids = {
            value
            for relationship in relationships
            if valid_pairs(relationship.column_pairs)
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
        rows = (await self._db.execute(stmt)).all()
        return {column.id: (table.physical_schema, table.table_name, column.column_name) for column, table in rows}

    async def load_metric_plan_metadata(self, connection_id: int) -> MetricPlanMetadata:
        tables_list = await self.load_tables(connection_id)
        counts = {
            table.table_name.casefold(): sum(
                t.table_name.casefold() == table.table_name.casefold() for t in tables_list
            )
            for table in tables_list
        }
        tables = {self._table_key(table, counts): table for table in tables_list}
        tables_folded = {key.casefold(): table for key, table in tables.items()}
        for table in tables_list:
            if table.physical_schema:
                tables_folded[f"{table.physical_schema}.{table.table_name}".casefold()] = table
        tables_by_id = {table.id: table for table in tables_list}
        columns, columns_by_id = await self._load_plan_columns(tables_list, tables_by_id, counts)
        result = await self._db.execute(
            select(CanonicalRelationshipModel).where(
                CanonicalRelationshipModel.connection_id == connection_id, *active_relationship_filters()
            )
        )
        relationships = list(result.scalars().all())
        relationship_columns = await self._relationship_columns(relationships)
        return MetricPlanMetadata(
            tables, tables_folded, tables_by_id, columns, columns_by_id, relationships, relationship_columns, {}, {}
        )

    async def _load_plan_columns(
        self,
        tables: list[SemanticTableModel],
        tables_by_id: dict[int, SemanticTableModel],
        counts: dict[str, int],
    ) -> tuple[dict[str, dict[str, tuple[str, int, str]]], dict[int, tuple[str, str, int, str]]]:
        result = await self._db.execute(
            select(SemanticColumnModel).where(SemanticColumnModel.table_id.in_([table.id for table in tables]))
        )
        columns: dict[str, dict[str, tuple[str, int, str]]] = {}
        columns_by_id: dict[int, tuple[str, str, int, str]] = {}
        for column in result.scalars().all():
            table = tables_by_id[column.table_id]
            data_type = column.data_type or ""
            key = self._table_key(table, counts)
            columns.setdefault(key, {})[column.column_name] = (column.column_name, column.id, data_type)
            columns_by_id[column.id] = (key, column.column_name, column.id, data_type)
        return columns, columns_by_id

    @staticmethod
    def _table_key(table: SemanticTableModel, counts: dict[str, int]) -> str:
        return (
            f"{table.physical_schema}.{table.table_name}"
            if counts[table.table_name.casefold()] > 1
            else table.table_name
        )

    def resolve_plan_stages(
        self,
        plan: MetricQueryPlan,
        metadata: MetricPlanMetadata,
        metric: SemanticMetricModel,
        definition: MetricDefinition,
    ) -> None:
        for stage in plan.stages:
            if stage.source_stage:
                self._inherit_plan_stage(stage, plan, metadata)
            else:
                self._resolve_source_plan_stage(stage, metadata, metric, definition)

    def _inherit_plan_stage(self, stage: MetricPlanStage, plan: MetricQueryPlan, metadata: MetricPlanMetadata) -> None:
        metadata.stage_tables[stage.name] = set(metadata.stage_tables[stage.source_stage])
        parent = next(item for item in plan.stages if item.name == stage.source_stage)
        for field in stage.group_by:
            if field.column_id is None:
                field_name = field.expression.split(".", 1)[-1]
                field.column_id = next((item.column_id for item in parent.group_by if item.name == field_name), None)

    def _resolve_source_plan_stage(
        self,
        stage: MetricPlanStage,
        metadata: MetricPlanMetadata,
        metric: SemanticMetricModel,
        definition: MetricDefinition,
    ) -> None:
        base = metadata.tables_folded.get(stage.base_entity.casefold())
        ids = {value for value in (metric.base_entity_id, definition.metric.base_entity_id) if value is not None}
        if len(ids) > 1:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric base IDs disagree")
        if stage.base_entity.casefold() == definition.metric.base_entity.casefold() and ids:
            selected = metadata.tables_by_id.get(next(iter(ids)))
            if selected is None or stage.base_entity.casefold() not in {
                selected.table_name.casefold(),
                f"{selected.physical_schema}.{selected.table_name}".casefold(),
            }:
                raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric base ID does not match its source")
            base = selected
        if base is None:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric plan references an unknown source table")
        stage.base_entity = next(key for key, table in metadata.tables.items() if table.id == base.id)
        metadata.stage_tables[stage.name] = {stage.base_entity}
        stage.joins = self._resolve_plan_joins(stage, base, metadata)
        self._resolve_group_dimension_joins(stage, base, metadata)
        self._resolve_plan_group_fields(stage, metadata)
        self._resolve_plan_stage_filters(stage, metadata)

    def _resolve_group_dimension_joins(
        self, stage: MetricPlanStage, base: SemanticTableModel, metadata: MetricPlanMetadata
    ) -> None:
        for field in stage.group_by:
            resolved = metadata.columns_by_id.get(field.column_id) if field.column_id is not None else None
            if resolved is None or resolved[0] in metadata.stage_tables[stage.name]:
                continue
            target = metadata.tables[resolved[0]]
            target_key = resolved[0]
            if target.id == base.id:
                continue
            path = _safe_join_path(metadata.relationships, base.id, target.id)
            metadata.join_paths[(stage.base_entity, target_key)] = self._plan_join_records(stage, path, metadata)
            stage.joins.append(target_key)

    def _resolve_plan_joins(
        self, stage: MetricPlanStage, base: SemanticTableModel, metadata: MetricPlanMetadata
    ) -> list[str]:
        resolved_joins = []
        for requested in list(stage.joins):
            target = metadata.tables_folded.get(requested.casefold())
            if target is None:
                raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric plan references an unknown joined table")
            if target.id == base.id:
                raise SemanticCompileError("UNSAFE_JOIN", "Metric plan cannot join its source table to itself")
            path = _safe_join_path(metadata.relationships, base.id, target.id)
            target_key = next(key for key, table in metadata.tables.items() if table.id == target.id)
            metadata.join_paths[(stage.base_entity, target_key)] = self._plan_join_records(stage, path, metadata)
            resolved_joins.append(target_key)
        return list(dict.fromkeys(resolved_joins))

    def _plan_join_records(
        self, stage: MetricPlanStage, path: list[RelationshipStep], metadata: MetricPlanMetadata
    ) -> list[dict[str, str]]:
        joins = []
        for relationship in path:
            target = metadata.tables_by_id[relationship.to_entity_id]
            joins.append(
                {
                    "relationship_id": relationship.id,
                    "table_name": target.table_name,
                    "physical_schema": target.physical_schema,
                    "condition": _relationship_condition(relationship, metadata.relationship_columns),
                    "table_key": next(key for key, table in metadata.tables.items() if table.id == target.id),
                }
            )
            metadata.stage_tables[stage.name].add(
                next(key for key, table in metadata.tables.items() if table.id == target.id)
            )
        return joins

    def _resolve_plan_group_fields(self, stage: MetricPlanStage, metadata: MetricPlanMetadata) -> None:
        for field in stage.group_by:
            resolved = self._resolve_plan_group_field(field, stage, metadata)
            if not resolved or resolved[0] not in metadata.stage_tables[stage.name]:
                raise SemanticCompileError(
                    "UNKNOWN_REFERENCE", "Metric plan grouping key does not match its source tables"
                )
            field.column_id = resolved[2]
            field.expression = f"{resolved[0]}.{resolved[1]}"

    def _resolve_plan_group_field(
        self, field: MetricPlanField, stage: MetricPlanStage, metadata: MetricPlanMetadata
    ) -> tuple[str, str, int, str] | None:
        if field.column_id is not None:
            return metadata.columns_by_id.get(field.column_id)
        parsed = sqlglot.parse_one(field.expression)
        if not isinstance(parsed, exp.Column):
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric plan grouping key must be a column")
        source_name = f"{parsed.db}.{parsed.table}" if parsed.db else (parsed.table or stage.base_entity)
        if parsed.db and (table := metadata.tables_folded.get(source_name.casefold())) is not None:
            source_name = next((k for k, v in metadata.tables.items() if v.id == table.id), source_name)
        matches = [
            key
            for key in metadata.stage_tables[stage.name]
            if key.casefold() == source_name.casefold()
            or (not parsed.db and key.rsplit(".", 1)[-1].casefold() == source_name.casefold())
        ]
        source_name = matches[0] if len(matches) == 1 else source_name
        return next(
            (
                (source_name, name, column_id, data_type)
                for name, (name, column_id, data_type) in metadata.columns.get(source_name, {}).items()
                if name.casefold() == parsed.name.casefold()
            ),
            None,
        )

    def _resolve_plan_stage_filters(self, stage: MetricPlanStage, metadata: MetricPlanMetadata) -> None:
        for aggregate in stage.aggregates:
            for filter_item in aggregate.filters:
                self._resolve_plan_filter_field(filter_item, stage, metadata)
        for filter_item in stage.filters:
            self._resolve_plan_filter_field(filter_item, stage, metadata)

    def _resolve_plan_filter_field(
        self, filter_item: MetricPlanFilter, stage: MetricPlanStage, metadata: MetricPlanMetadata
    ) -> None:
        if filter_item.column_id is None:
            return
        resolved = metadata.columns_by_id.get(filter_item.column_id)
        if not resolved or resolved[0] not in metadata.stage_tables[stage.name]:
            raise SemanticCompileError("UNKNOWN_REFERENCE", "Metric plan filter does not match its source tables")
        filter_item.field = f"{resolved[0]}.{resolved[1]}"

    def apply_plan_filters(
        self,
        plan: MetricQueryPlan,
        definition: MetricDefinition,
        runtime_filters: list[dict[str, Any]],
        metadata: MetricPlanMetadata,
        dialect: str = "postgres",
    ) -> None:
        scoped_filters = [
            {"column_id": item.column_id, "operator": item.operator, "value": item.value}
            for item in definition.metric.filters
        ] + runtime_filters
        for item in scoped_filters:
            stages, resolved = resolve_scoped_filter_stages(
                item["column_id"], plan.stages, metadata.stage_tables, metadata.columns_by_id
            )
            for stage in stages:
                self._append_plan_filter(stage, item, resolved, dialect)

    @staticmethod
    def _append_plan_filter(
        stage: MetricPlanStage,
        item: dict[str, Any],
        resolved: tuple[str, str, int, str],
        dialect: str = "postgres",
    ) -> None:
        operator = item["operator"]
        raw_value = item["value"]
        data_type = resolved[3]
        if operator in {"is_null", "is_not_null"}:
            validate_null_filter_value(raw_value, data_type, dialect)
            value = None
        elif operator in {"in", "not_in"}:
            value = coerce_sequence_filter_values(raw_value, data_type, dialect)
        elif operator == "between":
            value = coerce_sequence_filter_values(raw_value, data_type, dialect, expected_length=2)
        else:
            value = coerce_filter_value(raw_value, data_type, dialect)
        stage.filters.append(
            MetricPlanFilter.model_construct(
                field=f"{resolved[0]}.{resolved[1]}",
                operator=operator,
                value=value,
                column_id=item["column_id"],
            )
        )


@dataclass
class MetricPlanMetadata:
    """Schema and relationship metadata resolved while preparing a metric plan."""

    tables: dict[str, SemanticTableModel]
    tables_folded: dict[str, SemanticTableModel]
    tables_by_id: dict[int, SemanticTableModel]
    columns: dict[str, dict[str, tuple[str, int, str]]]
    columns_by_id: dict[int, tuple[str, str, int, str]]
    relationships: list[CanonicalRelationshipModel]
    relationship_columns: dict[int, tuple[str | None, str, str]]
    join_paths: dict[tuple[str, str], list[dict[str, str]]]
    stage_tables: dict[str, set[str]]


def _contains_fanout(path: list[RelationshipStep], relationships: list[CanonicalRelationshipModel]) -> bool:
    kinds = {item.id: item.relationship_type.replace("-", "_").lower() for item in relationships}
    return any(kinds[step.id] in {"one_to_many", "1:n"} for step in path)


def _exists_filter_record(
    item: dict[str, Any], path: list[RelationshipStep], columns: dict[int, tuple[str | None, str, str]]
) -> dict[str, Any]:
    return {
        "filter": item,
        "path": [
            {
                "relationship_id": step.id,
                "from_table_id": step.from_entity_id,
                "to_table_id": step.to_entity_id,
                "pairs": [
                    (
                        _relationship_column_data(pair["from_column_id"], columns),
                        _relationship_column_data(pair["to_column_id"], columns),
                    )
                    for pair in step.column_pairs
                ],
            }
            for step in path
        ],
    }


def _relationship_column_data(
    column_id: int, columns: dict[int, tuple[str | None, str, str]]
) -> tuple[str | None, str, str]:
    return columns[column_id]


def _relationship_condition(
    relationship: CanonicalRelationshipModel | RelationshipStep,
    columns: dict[int, tuple[str | None, str, str]],
) -> str:
    if relationship.column_pairs:
        predicates = [
            f"{_relationship_column(columns[pair['from_column_id']])} = {_relationship_column(columns[pair['to_column_id']])}"
            for pair in relationship.column_pairs
        ]
        return " AND ".join(predicates)
    raise SemanticCompileError(
        "RELATIONSHIP_NEEDS_REVIEW",
        "Relationship does not contain canonical column pairs",
        {"relationship_id": relationship.id},
    )


def _relationship_column(column: tuple[str | None, str, str]) -> str:
    return exp.column(column[2], table=column[1], db=column[0], quoted=True).sql()
