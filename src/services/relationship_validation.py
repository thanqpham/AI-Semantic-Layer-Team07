"""Metadata-only relationship validation and safe SQL previews."""

import re
from typing import Any, NoReturn

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from src.models.db import (
    ImportedSchemaModel,
    LiveTargetDbModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticTableModel,
)
from src.models.relationship_review import RelationshipDraft


def _invalid(
    code: str,
    message: str,
    *,
    field: str = "column_pairs",
    pair_index: int | None = None,
) -> NoReturn:
    """Raise a structured validation error identifying the invalid input."""
    raise HTTPException(
        status_code=422,
        detail={"errors": [{"code": code, "pair_index": pair_index, "field": field, "message": message}]},
    )


async def _endpoints(
    db: AsyncSession, db_id: int, draft: RelationshipDraft
) -> tuple[tuple[SemanticTableModel, list[SemanticColumnModel]], ...]:
    """Resolve both tables strictly within the requested semantic database."""
    if draft.from_entity_id == draft.to_entity_id:
        _invalid("REPEATED_TABLE", "Relationship endpoints must be different tables", field="to_entity_id")

    sides = []
    for field, entity_id in (
        ("from_entity_id", draft.from_entity_id),
        ("to_entity_id", draft.to_entity_id),
    ):
        table = await db.scalar(
            select(SemanticTableModel).where(
                SemanticTableModel.id == entity_id,
                SemanticTableModel.db_id == db_id,
            )
        )
        if table is None:
            _invalid("FOREIGN_TABLE", "Table does not belong to this database", field=field)
        columns = list(
            (await db.scalars(select(SemanticColumnModel).where(SemanticColumnModel.table_id == table.id))).all()
        )
        sides.append((table, columns))
    return tuple(sides)


def _type_family(value: str) -> str | None:
    """Normalize metadata types only where equality compatibility is established."""
    normalized = value.lower().strip()
    for family, pattern in (
        ("integer", r"^(smallint|bigint|integer|int\b)"),
        ("text", r"^(varchar|character varying|char\b|text)"),
    ):
        if re.match(pattern, normalized):
            return family
    if re.match(
        r"^(numeric|decimal|float|double|real|boolean|bool|uuid|date|time|timestamp|datetime|binary|varbinary)\b",
        normalized,
    ):
        return normalized.split()[0]
    return None


def _column_sql(table: SemanticTableModel, column: SemanticColumnModel, dialect: str) -> str:
    """Render a fully quoted qualified column with SQLGlot."""
    return exp.column(
        column.column_name,
        table=table.table_name,
        db=table.physical_schema,
        quoted=True,
    ).sql(dialect=dialect)


async def validate_relationship(
    db: AsyncSession,
    db_id: int,
    draft: RelationshipDraft,
    *,
    approval: bool = False,
) -> dict[str, Any]:
    """Validate metadata-only relationship proposals without contacting a target database."""
    if not draft.column_pairs:
        _invalid("EMPTY_PAIRS", "At least one column pair is required")
    sides = await _endpoints(db, db_id, draft)
    snapshot = await _source_snapshot(db, db_id)
    database = await db.get(SemanticDatabaseModel, db_id)
    dialect = _sqlglot_dialect(database.db_type if database is not None else "postgresql")
    seen: list[set[int]] = [set(), set()]
    clauses = await _pair_clauses(sides, snapshot, draft, seen, dialect)
    warnings = _cardinality_warnings(sides, seen, draft, approval)
    return {"sides": sides, "on_preview": " AND ".join(clauses), "warnings": warnings}


async def _pair_clauses(
    sides: tuple[tuple[SemanticTableModel, list[SemanticColumnModel]], ...],
    snapshot: list[dict[str, Any]] | None,
    draft: RelationshipDraft,
    seen: list[set[int]],
    dialect: str,
) -> list[str]:
    clauses = []
    for index, pair in enumerate(draft.column_pairs):
        source = _resolve_column(sides, snapshot, pair.from_column_id, 0, index, seen)
        target = _resolve_column(sides, snapshot, pair.to_column_id, 1, index, seen)
        if _type_family(source.data_type) is None or _type_family(source.data_type) != _type_family(target.data_type):
            _invalid("INCOMPATIBLE_TYPES", "Column types are not proven equality-compatible", pair_index=index)
        clauses.append(f"{_column_sql(sides[0][0], source, dialect)} = {_column_sql(sides[1][0], target, dialect)}")
    return clauses


def _resolve_column(
    sides: tuple[tuple[SemanticTableModel, list[SemanticColumnModel]], ...],
    snapshot: list[dict[str, Any]] | None,
    column_id: int,
    side: int,
    pair_index: int,
    seen: list[set[int]],
) -> SemanticColumnModel:
    table, columns = sides[side]
    column = next((candidate for candidate in columns if candidate.id == column_id), None)
    if column is None or column_id in seen[side]:
        _invalid("INVALID_PAIR", "Column is missing, belongs to another endpoint, or is reused", pair_index=pair_index)
    field = ("from_entity_id", "to_entity_id")[side]
    if snapshot is not None and not _snapshot_has_column(snapshot, table, column, field=field):
        _invalid("ABSENT_COLUMN", "Column is absent from the current physical schema", pair_index=pair_index)
    seen[side].add(column_id)
    return column


def _sqlglot_dialect(value: str) -> str:
    """Map database names to SQLGlot dialect identifiers."""
    return {"postgresql": "postgres", "sqlserver": "tsql", "mssql": "tsql"}.get(value, value)


def _cardinality_warnings(
    sides: tuple[tuple[SemanticTableModel, list[SemanticColumnModel]], ...],
    seen: list[set[int]],
    draft: RelationshipDraft,
    approval: bool,
) -> list[dict[str, str]]:
    """Require full key coverage or a human confirmation for unproven uniqueness."""
    warnings: list[dict[str, str]] = []
    required_sides = {
        "many_to_one": (1,),
        "one_to_one": (0, 1),
        "one_to_many": (0,),
        "many_to_many": (),
    }[draft.relationship_type]

    for side in required_sides:
        key_ids = {column.id for column in sides[side][1] if column.is_primary_key}
        warning = _required_key_warning(key_ids, seen[side], approval, draft.cardinality_confirmation)
        if warning:
            warnings.append(warning)
    if draft.relationship_type in {"one_to_many", "many_to_many"}:
        warnings.append({"code": "UNSAFE_FANOUT", "message": "This cardinality is unsafe for metric joins"})
    return warnings


def _required_key_warning(
    key_ids: set[int], pair_ids: set[int], approval: bool, confirmation: str | None
) -> dict[str, str] | None:
    if key_ids and pair_ids & key_ids and not key_ids <= pair_ids:
        _invalid("PARTIAL_COMPOSITE_KEY", "The complete composite key is required", pair_index=0)
    if key_ids and key_ids == pair_ids:
        return None
    if approval and not (confirmation or "").strip():
        _invalid(
            "UNPROVEN_CARDINALITY",
            "Explicit human uniqueness confirmation is required",
            field="cardinality_confirmation",
        )
    return {"code": "UNPROVEN_CARDINALITY", "message": "Uniqueness requires explicit human confirmation"}


async def _source_snapshot(db: AsyncSession, db_id: int) -> list[dict[str, Any]] | None:
    """Return the available live snapshot first, falling back to an imported snapshot."""
    for model in (LiveTargetDbModel, ImportedSchemaModel):
        schema_metadata = await db.scalar(
            select(model.schema_metadata)
            .where(model.semantic_db_id == db_id)
            .order_by(model.updated_at.desc(), model.id.desc())
            .limit(1)
        )
        if isinstance(schema_metadata, dict) and isinstance(schema_metadata.get("tables"), list):
            return schema_metadata["tables"]
    return None


def _snapshot_has_column(
    snapshot: list[dict[str, Any]],
    table: SemanticTableModel,
    column: SemanticColumnModel,
    *,
    field: str,
) -> bool:
    """Require a unique endpoint table and column match in a physical schema snapshot."""
    matches = [item for item in snapshot if _matches_snapshot_table(item, table)]
    if len(matches) != 1:
        _invalid(
            "ABSENT_TABLE",
            "Table is absent from the current physical schema",
            field=field,
        )
    return _snapshot_has_column_name(matches[0], column.column_name)


def _matches_snapshot_table(item: Any, table: SemanticTableModel) -> bool:
    if not isinstance(item, dict) or not isinstance(item.get("table_name"), dict):
        return False
    if item["table_name"].get("raw_name") != table.table_name:
        return False
    schema = item.get("schema_name")
    return table.physical_schema is None or (
        isinstance(schema, dict) and schema.get("raw_name") == table.physical_schema
    )


def _snapshot_has_column_name(table: dict[str, Any], column_name: str) -> bool:
    columns = table.get("columns")
    if not isinstance(columns, list):
        return False
    return any(
        isinstance(item, dict)
        and isinstance(item.get("column_name"), dict)
        and item["column_name"].get("raw_name") == column_name
        for item in columns
    )
